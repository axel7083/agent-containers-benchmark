"""Harbor CLI arguments per harness, all routed through the metering proxy.

Each harness gets the per-run client token as its API key and the proxy URL
as its base URL; the proxy forces the model and injects the real key.
"""

from __future__ import annotations

import json


def harbor_agent_args(harness: str, version: str, model: str, meter_url: str, client_token: str) -> list[str]:
    if harness == "claude-code":
        return [
            "-a", "claude-code", "--ak", f"version={version}", "-m", model,
            "--ae", f"ANTHROPIC_BASE_URL={meter_url}/api",
            "--ae", f"ANTHROPIC_API_KEY={client_token}",
        ]
    if harness == "codex":
        return [
            "-a", "codex", "--ak", f"version={version}", "-m", model,
            "--ae", f"OPENAI_BASE_URL={meter_url}/api/v1",
            "--ae", f"OPENAI_API_KEY={client_token}",
        ]
    if harness == "opencode":
        overlay = {"provider": {"openrouter": {"options": {"baseURL": f"{meter_url}/api/v1"}}}}
        return [
            "-a", "opencode", "--ak", f"version={version}", "-m", f"openrouter/{model}",
            "--ak", f"opencode_config={json.dumps(overlay)}",
            "--ae", f"OPENROUTER_API_KEY={client_token}",
        ]
    raise ValueError(f"unsupported harness {harness!r}")
