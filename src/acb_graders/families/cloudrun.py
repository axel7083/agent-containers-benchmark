"""`cloudrun`: the container honours Cloud Run's container runtime contract.

https://cloud.google.com/run/docs/container-contract: listen on 0.0.0.0:$PORT
(8080 by default), log to stdout/stderr, and shut down gracefully on SIGTERM
(SIGKILL follows 10 s later). Everything here is observed behaviour, so any
implementation strategy passes.
"""

from __future__ import annotations

import threading
import time

from .. import gates
from ..model import Artifacts, Check, Status

Result = tuple[Status, str]
ALT_PORT = 9123
ALT_HOST_PORT = 18081
ALT_CONTAINER = "acb-verify-port"


def collect(a: Artifacts, base_url: str, port: int, log: list[str]) -> None:
    cfg = a.spec.sections.get("cloudrun", {})
    facts: dict = {}

    # Logs: the gate already sent probes; a few more requests, then read stdout/stderr.
    for _ in range(3):
        gates.http_get(base_url + a.spec.probe.path)
    logs = gates.run(["podman", "logs", gates.CONTAINER], log=None)
    marker = cfg.get("log_marker", a.spec.probe.path)
    facts["logs_have_requests"] = marker in (logs.stdout + logs.stderr)

    # $PORT: a second container told to listen elsewhere.
    alt_base = f"http://127.0.0.1:{ALT_HOST_PORT}"
    env = {**a.spec.run.env, "PORT": str(ALT_PORT)}
    if gates.start_container(a, ALT_CONTAINER, ALT_HOST_PORT, ALT_PORT, env, log):
        _, ok = gates.wait_for_probe(a, ALT_CONTAINER, alt_base, timeout=40)
        facts["honours_port"] = ok
        slow = cfg.get("slow_path")
        if ok and slow:
            # Graceful shutdown: an in-flight request must complete after SIGTERM.
            outcome: dict = {}

            def request() -> None:
                outcome["status"], _ = gates.http_get(alt_base + slow, timeout=15)

            t = threading.Thread(target=request)
            t.start()
            time.sleep(0.7)
            gates.run(["podman", "kill", "-s", "TERM", ALT_CONTAINER], log=log)
            t.join(timeout=20)
            facts["drain_status"] = outcome.get("status")
            # A PID 1 that ignores SIGTERM also lets the request finish: it must actually exit afterwards.
            exited = False
            for _ in range(12):
                if gates.run(["podman", "inspect", "-f", "{{.State.Running}}", ALT_CONTAINER]).stdout.strip() != "true":
                    exited = True
                    break
                time.sleep(1)
            facts["drain_exited"] = exited
    else:
        facts["honours_port"] = False
    gates.run(["podman", "rm", "-f", ALT_CONTAINER])

    # Shutdown latency on the main container (after everything else).
    started = time.monotonic()
    gates.run(["podman", "stop", "-t", "10", gates.CONTAINER], timeout=30)
    facts["stop_seconds"] = round(time.monotonic() - started, 1)
    a.runtime.facts["cloudrun"] = facts


def _facts(a: Artifacts) -> dict | None:
    return a.runtime.facts.get("cloudrun")


def honours_port(a: Artifacts) -> Result:
    f = _facts(a)
    if f is None:
        return "fail", "the container did not serve on the default port"
    return ("pass", f"serves on PORT={ALT_PORT}") if f.get("honours_port") else ("fail", f"ignores PORT={ALT_PORT}")


def graceful_shutdown(a: Artifacts) -> Result:
    if not a.spec.sections.get("cloudrun", {}).get("slow_path"):
        return "na", "task has no long request"
    f = _facts(a)
    if f is None or not f.get("honours_port"):
        return "fail", "not measurable: the container does not honour PORT"
    status = f.get("drain_status")
    if status != 200:
        return "fail", f"in-flight request after SIGTERM -> {status}"
    if not f.get("drain_exited"):
        return "fail", "the process ignored SIGTERM (request finished only because nothing shut down)"
    return "pass", "in-flight request completed, then the container exited"


def fast_sigterm(a: Artifacts) -> Result:
    f = _facts(a)
    if f is None or "stop_seconds" not in f:
        return "fail", "the container did not run"
    secs = f["stop_seconds"]
    return ("pass" if secs < 5 else "fail"), f"`podman stop` took {secs}s (SIGKILL after 10s)"


def logs_to_stdout(a: Artifacts) -> Result:
    f = _facts(a)
    if f is None:
        return "fail", "the container did not run"
    return ("pass", "request logs on stdout/stderr") if f.get("logs_have_requests") else ("fail", "no request log on stdout/stderr")


CHECKS: tuple[Check, ...] = (
    Check(
        "honours-port-env", "maintainability", "Listen on 0.0.0.0 on the port given by the PORT environment variable (8080 by default).",
        ("app reads PORT", "server flag expanded from $PORT"), 1.0, True, honours_port,
        title="Honours $PORT",
        why="Cloud Run (and Heroku-style platforms) choose the port and pass it in `PORT`; a hard-coded port is never reached.",
        how=f"A second container is started with `PORT={ALT_PORT}` and must answer the probe on that port.",
    ),
    Check(
        "graceful-shutdown", "maintainability", "On SIGTERM, stop accepting new requests and finish in-flight ones before exiting.",
        ("production server with graceful shutdown (gunicorn, uvicorn, ...)", "app-level SIGTERM handler"), 1.0, True,
        graceful_shutdown,
        title="Drains in-flight requests on SIGTERM",
        why="Instances are stopped with SIGTERM during scale-in and deploys; dropping in-flight requests shows up as user errors.",
        how="A slow request is started, the container gets SIGTERM 0.7 s later; the request must still return 200 and the "
        "container must then exit on its own.",
        not_applicable="The task's app has no slow endpoint.",
    ),
    Check(
        "fast-sigterm", "maintainability", "Make sure the process receives SIGTERM and exits promptly (PID 1 signal handling).",
        ("exec-form CMD", "init process (tini, dumb-init)", "server that handles SIGTERM"), 1.0, True, fast_sigterm,
        title="Stops promptly on SIGTERM",
        why="A PID 1 that ignores SIGTERM (a shell wrapper, or an app without a handler) is killed after the grace period, "
        "every time: slow deploys and no cleanup.",
        how="Time of `podman stop -t 10`: under 5 s passes.",
    ),
    Check(
        "logs-to-stdout", "maintainability", "Write logs to stdout/stderr, not to files in the container.",
        ("logging to stdout/stderr", "server access log on stdout"), 1.0, True, logs_to_stdout,
        title="Logs to stdout/stderr",
        why="Cloud Run collects stdout/stderr; a log file inside an in-memory filesystem is lost and eats instance memory.",
        how="After a few requests, `podman logs` must mention the requested path.",
    ),
)
