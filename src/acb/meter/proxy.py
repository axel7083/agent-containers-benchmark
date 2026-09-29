"""Metering reverse proxy between agent sandboxes and OpenRouter.

Why it exists:
- The OpenRouter key never enters an agent container. Agents get a random
  per-run client token; the proxy swaps it for the real (capped, short-lived)
  key read from stdin at startup.
- Every request gets the same model forced, whatever the harness sends
  (some harnesses strip the provider prefix, others call "small/fast" models
  on the side).
- Cost of record is harness-agnostic: generation ids are captured from the
  responses and resolved against OpenRouter's `/generation` endpoint at
  shutdown, giving billed cost, provider and token counts per request.

Only the inference endpoints are forwarded; key management and account
endpoints are refused.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import signal
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

DEFAULT_UPSTREAM = "https://openrouter.ai"
ALLOWED = (
    ("POST", re.compile(r"^/api/v1/(messages|messages/count_tokens|responses|chat/completions)$")),
    ("GET", re.compile(r"^/api/v1/models(/.*)?$")),
)
GEN_ID = re.compile(rb"gen-[0-9A-Za-z_-]{8,}")
HOP_BY_HOP = {
    "host", "authorization", "x-api-key", "content-length", "connection", "keep-alive", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "accept-encoding", "cookie",
}
MAX_TEE = 32 * 1024 * 1024
# Generations resolved in parallel at shutdown (sequential lookups took up to 4 minutes per shard).
FINALIZE_CONCURRENCY = 8


class Meter:
    def __init__(self, model: str, log_path: Path, key: str, client_token: str) -> None:
        self.model = model
        self.log_path = log_path
        self._key = key
        self.client_token = client_token
        self.upstream = os.environ.get("ACB_METER_UPSTREAM", DEFAULT_UPSTREAM)
        self.generation_ids: list[str] = []
        self._session: ClientSession | None = None
        self._log = log_path.open("a", buffering=1)

    def record(self, entry: dict[str, Any]) -> None:
        self._log.write(json.dumps(entry) + "\n")

    def _authorized(self, request: web.Request) -> bool:
        presented = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return secrets.compare_digest(presented, self.client_token)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        started = time.time()
        path = request.path
        if not any(request.method == m and rx.match(path) for m, rx in ALLOWED):
            self.record({"type": "refused", "ts": started, "method": request.method, "path": path})
            return web.json_response({"error": "endpoint not allowed by acb-meter"}, status=403)
        if not self._authorized(request):
            self.record({"type": "unauthorized", "ts": started, "path": path})
            return web.json_response({"error": "bad client token"}, status=401)

        body = await request.read()
        requested_model = None
        if body and request.method == "POST":
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and "model" in payload:
                    requested_model = payload["model"]
                    payload["model"] = self.model
                    body = json.dumps(payload).encode()
            except ValueError:
                pass

        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Authorization"] = f"Bearer {self._key}"
        headers["Accept-Encoding"] = "identity"
        headers["HTTP-Referer"] = "https://github.com/axel7083/agent-containers-benchmark"
        headers["X-Title"] = "agent-containers-benchmark"

        assert self._session is not None
        entry: dict[str, Any] = {"type": "request", "ts": started, "method": request.method, "path": path, "requested_model": requested_model}
        try:
            async with self._session.request(request.method, self.upstream + request.path_qs, data=body or None, headers=headers) as upstream:
                response = web.StreamResponse(status=upstream.status)
                for k, v in upstream.headers.items():
                    if k.lower() not in HOP_BY_HOP and k.lower() != "content-encoding":
                        response.headers[k] = v
                await response.prepare(request)
                tee = bytearray()
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
                    if len(tee) < MAX_TEE:
                        tee.extend(chunk)
                await response.write_eof()
                ids = sorted({m.decode() for m in GEN_ID.findall(bytes(tee))})
                gen_header = upstream.headers.get("x-generation-id")
                if gen_header and gen_header not in ids:
                    ids.append(gen_header)
                self.generation_ids.extend(i for i in ids if i not in self.generation_ids)
                entry |= {"status": upstream.status, "bytes": len(tee), "generation_ids": ids}
                if upstream.status >= 400:
                    entry["error"] = bytes(tee[:600]).decode(errors="replace")
                return response
        except (ConnectionResetError, asyncio.CancelledError):
            entry["status"] = 499
            raise
        except Exception as exc:  # upstream/network failure: report as 502 to the agent
            entry |= {"status": 502, "error": f"{type(exc).__name__}: {exc}"}
            return web.json_response({"error": "acb-meter upstream failure"}, status=502)
        finally:
            entry["ts_end"] = time.time()
            self.record(entry)

    async def finalize(self) -> None:
        """Resolve billed cost per generation (concurrently), then the key's total usage."""
        assert self._session is not None
        auth = {"Authorization": f"Bearer {self._key}"}
        keep = ("model", "provider_name", "total_cost", "usage", "tokens_prompt", "tokens_completion",
                "native_tokens_prompt", "native_tokens_completion", "native_tokens_cached", "native_tokens_reasoning",
                "created_at", "finish_reason", "streamed", "latency", "generation_time", "cache_discount")
        limit = asyncio.Semaphore(FINALIZE_CONCURRENCY)

        async def resolve(gen_id: str) -> None:
            data = None
            async with limit:
                for attempt in range(5):
                    try:
                        async with self._session.get(
                            f"{self.upstream}/api/v1/generation", params={"id": gen_id}, headers=auth
                        ) as resp:
                            if resp.status == 200:
                                data = (await resp.json()).get("data")
                                break
                    except Exception:  # transient network error: retry like a 404
                        pass
                    await asyncio.sleep(1 + attempt * 2)
            self.record({"type": "generation", "id": gen_id, **({k: data.get(k) for k in keep} if data else {"missing": True})})

        await asyncio.gather(*(resolve(g) for g in self.generation_ids))
        async with self._session.get(f"{self.upstream}/api/v1/key", headers=auth) as resp:
            if resp.status == 200:
                info = (await resp.json()).get("data", {})
                self.record({"type": "key", **{k: info.get(k) for k in ("usage", "limit", "limit_remaining", "is_free_tier")}})

    async def run(self, host: str, port: int, stop: asyncio.Event) -> None:
        self._session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=30, sock_read=600))
        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        self.record({"type": "start", "ts": time.time(), "model": self.model})
        await stop.wait()
        await runner.cleanup()
        try:
            await self.finalize()
        finally:
            await self._session.close()
            self.record({"type": "stop", "ts": time.time()})
            self._log.close()


def serve(host: str, port: int, model: str, log: str, key: str) -> int:
    if not key.startswith("sk-or-") and not os.environ.get("ACB_METER_ALLOW_ANY_KEY"):
        raise SystemExit("acb-meter: expected an OpenRouter key on stdin")
    client_token = os.environ.get("ACB_METER_CLIENT_TOKEN")
    if not client_token:
        raise SystemExit("acb-meter: ACB_METER_CLIENT_TOKEN must be set")
    meter = Meter(model, Path(log), key, client_token)
    del key

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await meter.run(host, port, stop)

    asyncio.run(main())
    return 0
