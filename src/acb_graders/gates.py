"""Gates: does the agent's result work?

Runs inside the task container during Harbor's verify phase, after the agent
is done. Everything the agent built or started is removed first and the
artifact is rebuilt with `--no-cache`, so the grade reflects the files, not
leftover state. Three gate kinds exist:

- image:   Containerfile -> build -> run -> HTTP probe (optionally under
           platform constraints, e.g. an OpenShift-like arbitrary UID).
- kube:    Kubernetes manifests -> build the repo image -> `podman kube play`
           -> HTTP probe on the pod (see families/kube.py).
- quadlet: Quadlet units -> generator dry-run (see families/quadlet.py).
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

IMAGE = "localhost/acb-verify:v1"
CONTAINER = "acb-verify"
HOST_PORT = 18080
BUILD_TIMEOUT = 900
START_TIMEOUT = 60

# Gates run in order; the first failing one is the trial's failure class.
GATES_BY_KIND: dict[str, tuple[dict[str, str], ...]] = {
    "image": (
        {"id": "artifact", "title": "Artifact", "description": "A `Containerfile` or `Dockerfile` exists in the app directory."},
        {"id": "build", "title": "Build", "description": "The grader removes the agent's containers and pods, then rebuilds the file "
         "with `podman build --no-cache`. The agent's own images are never trusted."},
        {"id": "start", "title": "Start", "description": "`podman run -d -p 18080:<port>` starts the image (with the task's platform "
         "constraints, if any) and the container keeps running."},
        {"id": "probe", "title": "Probe", "description": "An HTTP request to the task's probe path returns the expected status and "
         "body within 60 seconds."},
    ),
    "kube": (
        {"id": "artifact", "title": "Manifests", "description": "YAML files in the app directory define at least one workload "
         "(Pod, Deployment, StatefulSet, DaemonSet, ReplicaSet or Job)."},
        {"id": "build", "title": "Build", "description": "The repository's Containerfile is rebuilt with `podman build --no-cache`; "
         "the workloads' images are pointed at it for the local run."},
        {"id": "start", "title": "Start", "description": "`podman kube play` runs the manifests and the pod reaches Running. "
         "Secrets and ConfigMaps the manifests reference but leave to the cluster are provided with placeholder values."},
        {"id": "probe", "title": "Probe", "description": "An HTTP request to the pod's container port answers the probe path "
         "within 60 seconds."},
    ),
    "quadlet": (
        {"id": "artifact", "title": "Units", "description": "Quadlet unit files (`.container`, `.pod`, `.kube`, `.volume`, "
         "`.network`, `.image`, `.build`) exist in the app directory."},
        {"id": "validate", "title": "Generate", "description": "Podman's Quadlet generator (`quadlet -dryrun`) turns them into "
         "systemd services without errors."},
    ),
}

FAILURE_CLASS_HELP: dict[str, str] = {
    "none": "All gates passed.",
    "no-artifact": "The agent produced no artifact of the expected kind.",
    "build": "The rebuild failed.",
    "start": "The container or pod exited, or could not be created.",
    "probe": "It runs, but the probe never succeeded.",
    "validate": "The Quadlet generator rejected the units.",
    "timeout": "The agent did not finish within the task's time limit (counted as a failure).",
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

    def fail(self, gate: str, failure_class: str | None = None) -> "GateResult":
        self.gates[gate] = False
        self.failure_class = failure_class or gate
        return self


def run(args: list[str], timeout: int = 120, log: list[str] | None = None, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    if log is not None:
        tail = (proc.stdout + proc.stderr)[-4000:]
        log.append(f"$ {' '.join(args)}\n[exit {proc.returncode}]\n{tail}")
    return proc


_run = run  # backwards-compatible name


def http_get(url: str, timeout: float = 3) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read(65536).decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except (urllib.error.URLError, OSError):
        return None, ""


def http_request(url: str, method: str, body: bytes | None = None, timeout: float = 5) -> int | None:
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(65536)
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, OSError):
        return None


def probe_ok(a: Artifacts, base_url: str) -> bool:
    status, body = http_get(base_url + a.spec.probe.path)
    if status != a.spec.probe.expect_status:
        return False
    return a.spec.probe.expect_body is None or a.spec.probe.expect_body in body


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
    run(["podman", "pod", "rm", "-a", "-f"], log=log)
    run(["podman", "rm", "-a", "-f"], log=log)


def looks_like_infra(stderr: str) -> bool:
    markers = ("toomanyrequests", "rate limit", "i/o timeout", "TLS handshake timeout", "no space left on device")
    return any(m.lower() in stderr.lower() for m in markers)


def build_image(a: Artifacts, res: GateResult) -> bool:
    """Pristine rebuild of the app's Containerfile into IMAGE."""
    reset_engine(res.log)
    try:
        build = run(
            ["podman", "build", "--no-cache", "--pull=missing", "-t", IMAGE, "-f", str(a.containerfile_path), str(a.context_dir)],
            timeout=BUILD_TIMEOUT,
            log=res.log,
        )
    except subprocess.TimeoutExpired:
        res.log.append("build timed out")
        res.fail("build")
        return False
    res.gates["build"] = build.returncode == 0
    if build.returncode != 0:
        res.failure_class = "infra" if looks_like_infra(build.stderr) else "build"
        return False
    return True


def run_gates(a: Artifacts) -> GateResult:
    if a.spec.gate == "kube":
        from .families import kube

        return kube.run_gates(a)
    if a.spec.gate == "quadlet":
        from .families import quadlet

        return quadlet.run_gates(a)
    return run_image_gates(a)


def image_port(a: Artifacts) -> int:
    if a.spec.run.port_from_image:
        exposed = a.runtime.facts.get("image", {}).get("exposed_ports") or []
        if exposed:
            return exposed[0]
    return a.spec.port


def start_container(a: Artifacts, name: str, host_port: int, port: int, env: dict[str, str], log: list[str]) -> bool:
    args = ["podman", "run", "-d", "--name", name, "-p", f"{host_port}:{port}"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += list(a.spec.run.args) + [IMAGE]
    return run(args, log=log).returncode == 0


def wait_for_probe(a: Artifacts, name: str, base_url: str, timeout: float = START_TIMEOUT) -> tuple[bool, bool]:
    """Returns (running, probe_ok)."""
    deadline = time.monotonic() + timeout
    running = False
    while time.monotonic() < deadline:
        running = run(["podman", "inspect", "-f", "{{.State.Running}}", name]).stdout.strip() == "true"
        if not running:
            return False, False
        if probe_ok(a, base_url):
            return True, True
        time.sleep(1)
    return running, False


def run_image_gates(a: Artifacts) -> GateResult:
    res = GateResult()
    log = res.log
    if a.containerfile_path is None:
        return res.fail("artifact", "no-artifact")
    res.gates["artifact"] = True

    if shutil.which("hadolint"):
        proc = run(["hadolint", "--no-fail", "--format", "json", str(a.containerfile_path)], log=log)
        try:
            a.runtime.hadolint = json.loads(proc.stdout or "[]")
        except ValueError:
            a.runtime.hadolint = None

    if not build_image(a, res):
        return res
    inspect_image(a, log)

    port = image_port(a)
    base = f"http://127.0.0.1:{HOST_PORT}"
    if not start_container(a, CONTAINER, HOST_PORT, port, a.spec.run.env, log):
        return res.fail("start")
    running, ok = wait_for_probe(a, CONTAINER, base)
    res.gates["start"] = running or ok
    if not res.gates["start"]:
        run(["podman", "logs", "--tail", "50", CONTAINER], log=log)
        return res.fail("start")
    res.gates["probe"] = ok
    if not ok:
        run(["podman", "logs", "--tail", "50", CONTAINER], log=log)
        res.failure_class = "probe"
    inspect_container(a, log)

    # Family-specific runtime observations (only meaningful on a running container).
    from .families import RUNTIME_HOOKS

    for family in a.spec.families:
        hook = RUNTIME_HOOKS.get(family)
        if hook and ok:
            try:
                hook(a, base, port, log)
            except Exception as exc:  # a broken hook must not sink the grade; its checks will report "error"
                log.append(f"{family} runtime hook failed: {type(exc).__name__}: {exc}")
    return res


def inspect_image(a: Artifacts, log: list[str]) -> None:
    proc = run(["podman", "image", "inspect", IMAGE], log=None)
    if proc.returncode != 0:
        return
    info = json.loads(proc.stdout)[0]
    a.runtime.image_size_bytes = int(info.get("Size") or 0)
    config = info.get("Config") or {}
    a.runtime.image_user = config.get("User") or ""
    a.runtime.image_healthcheck = bool(info.get("HealthCheck") or config.get("Healthcheck"))
    ports = []
    for key in (config.get("ExposedPorts") or {}):
        number = key.split("/")[0]
        if number.isdigit():
            ports.append(int(number))
    a.runtime.facts["image"] = {
        "exposed_ports": sorted(ports),
        "env": config.get("Env") or [],
        "layers": len((info.get("RootFS") or {}).get("Layers") or []),
    }

    if a.spec.canary_value:
        hist = run(["podman", "history", "--no-trunc", "--format", "{{.CreatedBy}}", IMAGE])
        a.runtime.canary_in_history = a.spec.canary_value in hist.stdout
        a.runtime.canary_in_filesystem = _canary_in_filesystem(a, log)


def mounted_image(log: list[str]):
    """Context manager yielding the rebuilt image's root filesystem path (or None)."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        mount = run(["podman", "image", "mount", IMAGE], log=log)
        if mount.returncode != 0:
            yield None
            return
        try:
            yield Path(mount.stdout.strip())
        finally:
            run(["podman", "image", "unmount", IMAGE])

    return _cm()


def _canary_in_filesystem(a: Artifacts, log: list[str]) -> bool | None:
    needle = a.spec.canary_value.encode()
    with mounted_image(log) as root:
        if root is None:
            return None
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


def inspect_container(a: Artifacts, log: list[str]) -> None:
    if "--user" in a.spec.run.args or any(arg.startswith("--user=") for arg in a.spec.run.args):
        # The grader forced the user (platform emulation): the running uid says nothing about the image.
        return
    top = run(["podman", "top", CONTAINER, "huid"], log=log)
    uids: list[int] = []
    if top.returncode == 0:
        for line in top.stdout.splitlines()[1:]:
            parts = line.split()
            if parts and parts[0].isdigit():
                uids.append(int(parts[0]))
    if not uids:
        # Fall back to the in-container uid of PID 1.
        pid = run(["podman", "inspect", "-f", "{{.State.Pid}}", CONTAINER]).stdout.strip()
        status = Path(f"/proc/{pid}/status")
        if pid.isdigit() and status.exists():
            for line in status.read_text().splitlines():
                if line.startswith("Uid:"):
                    uids.append(int(line.split()[1]))
    a.runtime.process_uids = uids or None


def cleanup() -> None:
    run(["podman", "pod", "rm", "-a", "-f"])
    run(["podman", "rm", "-a", "-f"])
    run(["podman", "rmi", "-f", IMAGE])
