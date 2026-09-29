import asyncio
import json

from aiohttp import ClientSession, web

from acb.meter.proxy import Meter

KEY = "sk-or-v1-secret"
TOKEN = "client-token"


async def fake_openrouter(seen: list):
    async def completions(request: web.Request):
        seen.append({"auth": request.headers.get("Authorization"), "x-api-key": request.headers.get("x-api-key"), "body": await request.json()})
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        await resp.write(b'data: {"id":"gen-abc123456789","choices":[]}\n\n')
        await resp.write(b"data: [DONE]\n\n")
        return resp

    async def generation(request: web.Request):
        return web.json_response({"data": {"total_cost": 0.0123, "provider_name": "Fake", "tokens_prompt": 10, "model": "m"}})

    async def key(request: web.Request):
        return web.json_response({"data": {"usage": 0.0123, "limit": 1.0, "limit_remaining": 0.9877}})

    app = web.Application()
    app.router.add_post("/api/v1/chat/completions", completions)
    app.router.add_get("/api/v1/generation", generation)
    app.router.add_get("/api/v1/key", key)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_meter_forces_model_swaps_key_and_resolves_cost(tmp_path, monkeypatch, unused_tcp_port=18999):
    async def scenario():
        seen: list = []
        upstream_runner, upstream = await fake_openrouter(seen)
        monkeypatch.setenv("ACB_METER_UPSTREAM", upstream)
        log = tmp_path / "meter.jsonl"
        meter = Meter("z-ai/glm-5.3-flash", log, KEY, TOKEN)
        stop = asyncio.Event()
        task = asyncio.create_task(meter.run("127.0.0.1", unused_tcp_port, stop))
        await asyncio.sleep(0.3)
        base = f"http://127.0.0.1:{unused_tcp_port}"
        async with ClientSession() as s:
            async with s.post(f"{base}/api/v1/chat/completions", json={"model": "gpt-x", "stream": True},
                              headers={"Authorization": f"Bearer {TOKEN}"}) as r:
                text = await r.text()
                assert r.status == 200 and "gen-abc123456789" in text
            async with s.post(f"{base}/api/v1/chat/completions", json={"model": "x"}, headers={"Authorization": "Bearer nope"}) as r:
                assert r.status == 401
            async with s.get(f"{base}/api/v1/keys", headers={"Authorization": f"Bearer {TOKEN}"}) as r:
                assert r.status == 403
        stop.set()
        await task
        await upstream_runner.cleanup()
        return seen, [json.loads(line) for line in log.read_text().splitlines()]

    seen, entries = asyncio.run(scenario())
    assert seen == [{"auth": f"Bearer {KEY}", "x-api-key": None, "body": {"model": "z-ai/glm-5.3-flash", "stream": True}}]
    req = next(e for e in entries if e["type"] == "request")
    assert req["requested_model"] == "gpt-x" and req["generation_ids"] == ["gen-abc123456789"]
    gen = next(e for e in entries if e["type"] == "generation")
    assert gen["total_cost"] == 0.0123 and gen["provider_name"] == "Fake"
    assert next(e for e in entries if e["type"] == "key")["usage"] == 0.0123
    assert {e["type"] for e in entries} >= {"refused", "unauthorized", "start", "stop"}
    assert KEY not in (tmp_path / "meter.jsonl").read_text()
