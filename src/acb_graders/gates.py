"""Gates for the `containerfile` family: pristine rebuild, start, probe.

Runs inside the task container during Harbor's verify phase, after the agent
is done. Everything the agent built or started is removed first, then the
artifact is rebuilt with `--no-cache` so the grade reflects the Containerfile,
not leftover state.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .model import Artifacts

IMAGE = "localhost/acb-verify:latest"
CONTAINER = "acb-verify"
HOST_PORT = 18080
BUILD_TIMEOUT = 900
START_TIMEOUT = 60


# Gates run in this order; the first failing one is the trial's failure class.
GATES: tuple[dict[str, str], ...] = (
    {"id": "artifact", "title": "Artifact", "description": "A `Containerfile` or `Dockerfile` exists in the app directory."},
    {"id": "build", "title": "Build", "description": "The grader removes the agent's containers and pods, then rebuilds the file with "
     "`podman build --no-cache`. The agent's own images are never trusted."},
    {"id": "start", "title": "Start", "description": "`podman run -d -p 18080:<port>` starts the image and the container keeps running."},
    {"id": "probe", "title": "Probe", "description": "An HTTP request to the task's probe path returns the expected status and body "
     "within 60 seconds."},
)

FAILURE_CLASS_HELP: dict[str, str] = {
    "none": "All gates passed.",
    "no-artifact": "The agent produced no Containerfile/Dockerfile.",
    "build": "The rebuild failed.",
    "start": "The container exited or could not be created.",
    "probe": "The container runs but the probe never succeeded.",
    "infra": "Infrastructure problem (registry rate limit, disk, grader crash); excluded from scores.",
    "budget": "The shard's OpenRouter spending cap was hit; excluded from scores.",
    "no-verdict": "No grader result was produced; excluded from scores.",
}


@dataclass
class GateResult:
    gates: dict[str, bool] = field(default_factory=dict)
    failure_class: str = "none"
    log: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.failure_class == "none"


def _run(args: list[str], timeout: int = 120, log: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if log is not None:
        tail = (proc.stdout + proc.stderr)[-4000:]
        log.append(f"$ {' '.join(args)}\n[exit {proc.returncode}]\n{tail}")
    return proc


def find_containerfile(app_dir: Path) -> Path | None:
    for name in ("Containerfile", "Dockerfile", "containerfile", "dockerfile"):
        if (app_dir / name).is_file():
            return app_dir / name
    candidates = sorted(
        p for p in app_dir.rglob("*")
        if p.is_file() and p.name.lower().split(".")[0] in ("containerfile", "dockerfile")
        and "node_modules" not in p.parts and len(p.relative_to(app_dir).parts) <= 3
    )
    return candidates[0] if candidates else None


def reset_engine(log: list[str]) -> None:
    """Remove the agent's containers and pods; keep pulled base images (cache, not state)."""
    _run(["podman", "pod", "rm", "-a", "-f"], log=log)
    _run(["podman", "rm", "-a", "-f"], log=log)


def run_gates(a: Artifacts) -> GateResult:
    res = GateResult()
    log = res.log
    if a.containerfile_path is None:
        res.gates["artifact"] = False
        res.failure_class = "no-artifact"
        return res
    res.gates["artifact"] = True

    if shutil.which("hadolint"):
        proc = _run(["hadolint", "--no-fail", "--format", "json", str(a.containerfile_path)], log=log)
        try:
            a.runtime.hadolint = json.loads(proc.stdout or "[]")
        except ValueError:
            a.runtime.hadolint = None

    reset_engine(log)
    try:
        build = _run(
            ["podman", "build", "--no-cache", "--pull=missing", "-t", IMAGE, "-f", str(a.containerfile_path), str(a.context_dir)],
            timeout=BUILD_TIMEOUT,
            log=log,
        )
    except subprocess.TimeoutExpired:
        res.gates["build"] = False
        res.failure_class = "build"
        log.append("build timed out")
        return res
    res.gates["build"] = build.returncode == 0
    if build.returncode != 0:
        res.failure_class = "infra" if _looks_like_infra(build.stderr) else "build"
        return res

    inspect_image(a, log)

    run = _run(["podman", "run", "-d", "--name", CONTAINER, "-p", f"{HOST_PORT}:{a.spec.port}", IMAGE], log=log)
    if run.returncode != 0:
        res.gates["start"] = False
        res.failure_class = "start"
        return res

    probe_ok, running = False, False
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        state = _run(["podman", "inspect", "-f", "{{.State.Running}}", CONTAINER]).stdout.strip()
        running = state == "true"
        if not running:
            break
        if _probe(a):
            probe_ok = True
            break
        time.sleep(1)
    res.gates["start"] = running or probe_ok
    if not res.gates["start"]:
        _run(["podman", "logs", "--tail", "50", CONTAINER], log=log)
        res.failure_class = "start"
        return res
    res.gates["probe"] = probe_ok
    if not probe_ok:
        _run(["podman", "logs", "--tail", "50", CONTAINER], log=log)
        res.failure_class = "probe"
    inspect_container(a, log)
    return res


def _looks_like_infra(stderr: str) -> bool:
    markers = ("toomanyrequests", "rate limit", "i/o timeout", "TLS handshake timeout", "no space left on device")
    return any(m.lower() in stderr.lower() for m in markers)


def _probe(a: Artifacts) -> bool:
    url = f"http://127.0.0.1:{HOST_PORT}{a.spec.probe.path}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = resp.read(65536).decode(errors="replace")
            status = resp.status
    except urllib.error.HTTPError as err:
        status, body = err.code, ""
    except (urllib.error.URLError, OSError):
        return False
    if status != a.spec.probe.expect_status:
        return False
    return a.spec.probe.expect_body is None or a.spec.probe.expect_body in body


def inspect_image(a: Artifacts, log: list[str]) -> None:
    proc = _run(["podman", "image", "inspect", IMAGE], log=None)
    if proc.returncode != 0:
        return
    info = json.loads(proc.stdout)[0]
    a.runtime.image_size_bytes = int(info.get("Size") or 0)
    config = info.get("Config") or {}
    a.runtime.image_user = config.get("User") or ""
    a.runtime.image_healthcheck = bool(info.get("HealthCheck") or config.get("Healthcheck"))

    if a.spec.canary_value:
        hist = _run(["podman", "history", "--no-trunc", "--format", "{{.CreatedBy}}", IMAGE])
        a.runtime.canary_in_history = a.spec.canary_value in hist.stdout
        a.runtime.canary_in_filesystem = _canary_in_filesystem(a, log)


def _canary_in_filesystem(a: Artifacts, log: list[str]) -> bool | None:
    mount = _run(["podman", "image", "mount", IMAGE], log=log)
    if mount.returncode != 0:
        return None
    root = Path(mount.stdout.strip())
    needle = a.spec.canary_value.encode()
    try:
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            if any(part in ("proc", "sys", "usr", "lib", "lib64", "bin", "sbin") for part in path.relative_to(root).parts[:1]):
                continue
            try:
                if path.stat().st_size > 5_000_000:
                    continue
                if needle in path.read_bytes():
                    log.append(f"canary found in {path.relative_to(root)}")
                    return True
            except OSError:
                continue
        return False
    finally:
        _run(["podman", "image", "unmount", IMAGE])


def inspect_container(a: Artifacts, log: list[str]) -> None:
    top = _run(["podman", "top", CONTAINER, "huid"], log=log)
    uids: list[int] = []
    if top.returncode == 0:
        for line in top.stdout.splitlines()[1:]:
            parts = line.split()
            if parts and parts[0].isdigit():
                uids.append(int(parts[0]))
    if not uids:
        # Fall back to the in-container uid of PID 1.
        pid = _run(["podman", "inspect", "-f", "{{.State.Pid}}", CONTAINER]).stdout.strip()
        status = Path(f"/proc/{pid}/status")
        if pid.isdigit() and status.exists():
            for line in status.read_text().splitlines():
                if line.startswith("Uid:"):
                    uids.append(int(line.split()[1]))
    a.runtime.process_uids = uids or None


def cleanup() -> None:
    _run(["podman", "rm", "-f", CONTAINER])
    _run(["podman", "rmi", "-f", IMAGE])
