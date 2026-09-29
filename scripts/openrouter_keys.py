#!/usr/bin/env python3
"""OpenRouter child-key lifecycle. The ONLY code that sees the management key.

Runs exclusively in the `provision` and `revoke` jobs of benchmark.yml, which
never run agents. Stdlib-only on purpose: small enough to audit, no
third-party code executes next to the management key.

  provision: check credits, create one capped + expiring key per shard, seal
             each key with the repository's RSA public key (only the sealed
             blob leaves this job, as a job output).
  status:    read-only report of credits and live benchmark key usage.
  revoke:    record each child key's billed usage, delete it, and sweep any
             stale `acb-` key left behind by an aborted run.

The management key is read from the OPENROUTER_MANAGEMENT_KEY environment
variable and is never printed, written to disk, or passed to a subprocess.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://openrouter.ai/api/v1"
PREFIX = "acb-"
EXPIRY_HOURS = 5
STALE_HOURS = 6


def _mgmt_key() -> str:
    key = os.environ.get("OPENROUTER_MANAGEMENT_KEY", "")
    if not key:
        sys.exit("OPENROUTER_MANAGEMENT_KEY is not set")
    return key


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_mgmt_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        # Never echo request headers; the response body carries no secret.
        raise SystemExit(f"OpenRouter {method} {path} -> HTTP {err.code}: {err.read()[:300]!r}") from None
    return json.loads(raw) if raw else {}


def _mask(value: str) -> None:
    # GitHub Actions masks the value in any later log line of this job.
    print(f"::add-mask::{value}", flush=True)


def _seal(secret: str, public_key_path: str) -> str:
    proc = subprocess.run(
        ["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", public_key_path,
         "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256"],
        input=secret.encode(), capture_output=True, check=True,
    )
    return base64.b64encode(proc.stdout).decode()


def remaining_credits() -> float | None:
    try:
        data = _call("GET", "/credits").get("data", {})
    except SystemExit as exc:
        print(f"warning: could not read credits ({exc})", file=sys.stderr)
        return None
    return float(data.get("total_credits", 0)) - float(data.get("total_usage", 0))


def provision(plan_path: str, run_id: str, public_key_path: str, max_total: float, out_path: str) -> None:
    plan = json.load(open(plan_path))
    # Expected spend, not the sum of caps: each cap also reserves one full-size request that is
    # normally never billed. The account balance (no auto top-up) remains the hard ceiling.
    expected = float(plan.get("total_est_usd", plan["total_cap_usd"]))
    caps = float(plan["total_cap_usd"])
    if expected > max_total:
        sys.exit(f"expected spend ${expected:.2f} exceeds the run budget ${max_total:.2f}")
    credits = remaining_credits()
    if credits is not None:
        print(f"credits remaining: ${credits:.2f}, expected spend: ${expected:.2f}, sum of key caps: ${caps:.2f}")
        if credits < expected:
            sys.exit("not enough OpenRouter credits for the expected spend")

    expires = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=EXPIRY_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sealed: dict[str, dict] = {}
    for shard in plan["shards"]:
        created = _call("POST", "/keys", {
            "name": f"{PREFIX}{run_id}-{shard['id']}"[:120],
            "limit": shard["cap_usd"],
            "expires_at": expires,
            "include_byok_in_limit": True,
        })
        key, key_hash = created["key"], created["data"]["hash"]
        _mask(key)
        sealed[shard["id"]] = {"hash": key_hash, "sealed": _seal(key, public_key_path)}
        del key
        print(f"created key for {shard['id']} (cap ${shard['cap_usd']}, expires {expires})")
    with open(out_path, "w") as fh:
        json.dump(sealed, fh)


def revoke(keys_json: str, run_id: str, out_path: str) -> None:
    keys = json.loads(keys_json or "{}")
    billing = {}
    for shard_id, entry in keys.items():
        key_hash = entry["hash"]
        try:
            info = _call("GET", f"/keys/{key_hash}").get("data", {})
            billing[shard_id] = {k: info.get(k) for k in ("usage", "limit", "limit_remaining", "created_at")}
        except SystemExit as exc:
            billing[shard_id] = {"error": str(exc)}
        try:
            _call("DELETE", f"/keys/{key_hash}")
            print(f"deleted key for {shard_id}")
        except SystemExit as exc:
            print(f"warning: delete failed for {shard_id}: {exc}", file=sys.stderr)

    # Sweep keys from aborted runs (expiry is the backstop; this is belt and braces).
    now = dt.datetime.now(dt.UTC)
    listed = _call("GET", "/keys").get("data", [])
    for info in listed:
        name = info.get("name") or info.get("label") or ""
        created = info.get("created_at")
        if not name.startswith(PREFIX) or not created:
            continue
        age = now - dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        if age > dt.timedelta(hours=STALE_HOURS):
            try:
                _call("DELETE", f"/keys/{info['hash']}")
                print(f"swept stale key {name}")
            except SystemExit as exc:
                print(f"warning: sweep failed for {name}: {exc}", file=sys.stderr)
    with open(out_path, "w") as fh:
        json.dump({"run_id": run_id, "shards": billing}, fh, indent=2)


def status() -> None:
    """Read-only: account credits and usage of every live benchmark key."""
    credits = remaining_credits()
    print(f"credits remaining: {'unknown' if credits is None else f'${credits:.2f}'}")
    total = 0.0
    for info in _call("GET", "/keys").get("data", []):
        name = info.get("name") or info.get("label") or ""
        if not name.startswith(PREFIX):
            continue
        usage = float(info.get("usage") or 0)
        total += usage
        print(f"{name:70s} usage=${usage:.4f} limit=${info.get('limit')} remaining=${info.get('limit_remaining')} disabled={info.get('disabled')}")
    print(f"live benchmark keys total usage: ${total:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("provision")
    p.add_argument("--plan", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--public-key", required=True)
    p.add_argument("--max-total", type=float, required=True)
    p.add_argument("--out", required=True)
    r = sub.add_parser("revoke")
    r.add_argument("--run-id", required=True)
    r.add_argument("--out", required=True)
    sub.add_parser("status")
    args = parser.parse_args()
    if args.cmd == "status":
        status()
    elif args.cmd == "provision":
        provision(args.plan, args.run_id, args.public_key, args.max_total, args.out)
    else:
        revoke(os.environ.get("ACB_KEYS_JSON", "{}"), args.run_id, args.out)


if __name__ == "__main__":
    main()
