"""`kube`: production-grade Kubernetes manifests, runnable with `podman kube play`.

Static checks follow the Pod Security Standards "restricted" profile and the
usual production hygiene. They resolve pod-level vs container-level settings
the way Kubernetes does (a pod-level `securityContext` applies to every
container unless overridden), so both placements pass. `podman kube play`
ignores some fields (runAsNonRoot, seccompProfile, readinessProbe,
automountServiceAccountToken), which is why they are checked statically.
"""

from __future__ import annotations

import time
from pathlib import Path

from .. import gates
from ..gates import GateResult
from ..model import Artifacts, Check, Status

Result = tuple[Status, str]
WORKLOAD_KINDS = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job"}
MANIFEST = "/tmp/acb-kube.yaml"


def load_documents(app: Path) -> list[tuple[str, dict]]:
    import yaml

    docs = []
    for path in sorted(list(app.rglob("*.yaml")) + list(app.rglob("*.yml"))):
        rel = path.relative_to(app)
        if any(part in ("node_modules", ".git", ".github") for part in rel.parts) or rel.name.startswith((".", "docker-compose", "compose")):
            continue
        try:
            for doc in yaml.safe_load_all(path.read_text()):
                if isinstance(doc, dict) and doc.get("kind"):
                    docs.append((rel.as_posix(), doc))
        except yaml.YAMLError:
            continue
    return docs


def pod_specs(docs: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """(name, pod spec) of every workload."""
    out = []
    for _, doc in docs:
        kind = doc.get("kind")
        if kind not in WORKLOAD_KINDS:
            continue
        name = f"{kind}/{(doc.get('metadata') or {}).get('name', '?')}"
        spec = doc.get("spec") or {}
        pod = spec if kind == "Pod" else ((spec.get("template") or {}).get("spec") or {})
        if kind == "Job" and not pod:
            pod = ((spec.get("template") or {}).get("spec") or {})
        out.append((name, pod))
    return out


def containers(pod: dict, include_init: bool = True) -> list[dict]:
    items = list(pod.get("containers") or [])
    if include_init:
        items += list(pod.get("initContainers") or [])
    return [c for c in items if isinstance(c, dict)]


def effective(pod: dict, container: dict, key: str):
    """Container securityContext value, falling back to the pod-level one."""
    c = (container.get("securityContext") or {}).get(key)
    return c if c is not None else (pod.get("securityContext") or {}).get(key)


def _facts(a: Artifacts) -> dict:
    return a.runtime.facts.setdefault("kube", {})


def _specs(a: Artifacts) -> list[tuple[str, dict]]:
    return _facts(a).get("_pods") or []


# --------------------------------------------------------------------- gates


def run_gates(a: Artifacts) -> GateResult:
    import yaml

    res = GateResult()
    docs = load_documents(a.app_dir)
    pods = pod_specs(docs)
    _facts(a)["_docs"] = docs
    _facts(a)["_pods"] = pods
    if not pods:
        return res.fail("artifact", "no-artifact")
    res.gates["artifact"] = True
    if a.containerfile_path is None:
        res.log.append("the repository has no Containerfile to build the workload image from")
        return res.fail("build")
    if not gates.build_image(a, res):
        return res
    gates.inspect_image(a, res.log)

    # Point every workload container at the image we just built, and keep only the kinds kube play runs.
    playable = []
    for _, doc in docs:
        doc = yaml.safe_load(yaml.safe_dump(doc))  # deep copy
        if doc.get("kind") in WORKLOAD_KINDS:
            pod = doc["spec"] if doc["kind"] == "Pod" else doc["spec"].setdefault("template", {}).setdefault("spec", {})
            for c in containers(pod, include_init=False):
                c["image"] = gates.IMAGE
                c["imagePullPolicy"] = "IfNotPresent"
            playable.append(doc)
        elif doc.get("kind") in ("Secret", "ConfigMap", "PersistentVolumeClaim"):
            playable.append(doc)
    Path(MANIFEST).write_text(yaml.safe_dump_all(playable))
    play = gates.run(["podman", "kube", "play", "--replace", MANIFEST], timeout=300, log=res.log)
    if play.returncode != 0:
        return res.fail("start")

    # Wait for an app container to be running, then probe the pod over its IP.
    deadline = time.monotonic() + gates.START_TIMEOUT
    container, ip, port = None, None, None
    while time.monotonic() < deadline:
        ps = gates.run(["podman", "ps", "--format", "{{.Names}} {{.Image}} {{.Pod}}"]).stdout.split("\n")
        app = [line.split() for line in ps if gates.IMAGE in line]
        if app:
            container, pod_id = app[0][0], app[0][2]
            infra = gates.run(["podman", "pod", "inspect", pod_id, "--format", "{{.InfraContainerID}}"]).stdout.strip()
            ip = gates.run(["podman", "inspect", infra, "--format",
                            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"]).stdout.strip()
            break
        time.sleep(1)
    if not container or not ip:
        gates.run(["podman", "ps", "-a"], log=res.log)
        return res.fail("start")
    res.gates["start"] = True
    for _, pod in pods:
        for c in containers(pod, include_init=False):
            for p in c.get("ports") or []:
                if isinstance(p, dict) and p.get("containerPort"):
                    port = int(p["containerPort"])
                    break
            if port:
                break
    port = port or a.spec.port
    base = f"http://{ip}:{port}"
    ok = False
    while time.monotonic() < deadline + 30:
        if gates.probe_ok(a, base):
            ok = True
            break
        if gates.run(["podman", "inspect", "-f", "{{.State.Running}}", container]).stdout.strip() != "true":
            break
        time.sleep(1)
    res.gates["probe"] = ok
    if not ok:
        gates.run(["podman", "logs", "--tail", "50", container], log=res.log)
        res.failure_class = "probe"
    inspect = gates.run(["podman", "inspect", container, "--format",
                         "{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.EffectiveCaps}}|{{.HostConfig.SecurityOpt}}"])
    _facts(a)["running"] = inspect.stdout.strip()
    return res


# -------------------------------------------------------------------- checks


def _all_containers(a: Artifacts, include_init: bool = True):
    for name, pod in _specs(a):
        for c in containers(pod, include_init):
            yield name, pod, c


def _no_workload() -> Result:
    return "fail", "no Kubernetes workload found"


def run_as_non_root(a: Artifacts) -> Result:
    items = list(_all_containers(a))
    if not items:
        return _no_workload()
    bad = []
    for name, pod, c in items:
        if effective(pod, c, "runAsNonRoot") is not True or effective(pod, c, "runAsUser") == 0:
            bad.append(f"{name}:{c.get('name')}")
    return ("fail", f"runAsNonRoot not true for {', '.join(bad)}") if bad else ("pass", "runAsNonRoot: true on every container")


def no_privilege_escalation(a: Artifacts) -> Result:
    items = list(_all_containers(a))
    if not items:
        return _no_workload()
    bad = [f"{n}:{c.get('name')}" for n, _, c in items if (c.get("securityContext") or {}).get("allowPrivilegeEscalation") is not False]
    return ("fail", f"allowPrivilegeEscalation not false for {', '.join(bad)}") if bad else ("pass", "allowPrivilegeEscalation: false everywhere")


def drop_all_capabilities(a: Artifacts) -> Result:
    items = list(_all_containers(a))
    if not items:
        return _no_workload()
    bad = []
    for n, _, c in items:
        caps = (c.get("securityContext") or {}).get("capabilities") or {}
        drop = [str(x).upper() for x in caps.get("drop") or []]
        add = [str(x).upper() for x in caps.get("add") or []]
        if "ALL" not in drop or any(x not in ("NET_BIND_SERVICE",) for x in add):
            bad.append(f"{n}:{c.get('name')}")
    return ("fail", f"capabilities not dropped for {', '.join(bad)}") if bad else ("pass", "drop: [ALL] everywhere")


def seccomp_runtime_default(a: Artifacts) -> Result:
    items = list(_all_containers(a))
    if not items:
        return _no_workload()
    bad = []
    for n, pod, c in items:
        profile = effective(pod, c, "seccompProfile") or {}
        if not isinstance(profile, dict) or profile.get("type") not in ("RuntimeDefault", "Localhost"):
            bad.append(f"{n}:{c.get('name')}")
    return ("fail", f"no RuntimeDefault seccomp for {', '.join(bad)}") if bad else ("pass", "seccompProfile RuntimeDefault/Localhost")


def read_only_root_filesystem(a: Artifacts) -> Result:
    items = list(_all_containers(a, include_init=False))
    if not items:
        return _no_workload()
    bad = [f"{n}:{c.get('name')}" for n, _, c in items if (c.get("securityContext") or {}).get("readOnlyRootFilesystem") is not True]
    return ("fail", f"writable root filesystem for {', '.join(bad)}") if bad else ("pass", "readOnlyRootFilesystem: true")


def resources(a: Artifacts) -> Result:
    items = list(_all_containers(a, include_init=False))
    if not items:
        return _no_workload()
    bad = []
    for n, _, c in items:
        r = c.get("resources") or {}
        req, lim = r.get("requests") or {}, r.get("limits") or {}
        if not (req.get("cpu") and req.get("memory") and lim.get("memory")):
            bad.append(f"{n}:{c.get('name')}")
    return ("fail", f"missing cpu/memory requests or memory limit for {', '.join(bad)}") if bad else ("pass", "requests and memory limit set")


def probes(a: Artifacts) -> Result:
    items = list(_all_containers(a, include_init=False))
    if not items:
        return _no_workload()
    bad = [f"{n}:{c.get('name')}" for n, _, c in items if not (c.get("livenessProbe") and c.get("readinessProbe"))]
    return ("fail", f"missing liveness/readiness probe for {', '.join(bad)}") if bad else ("pass", "liveness and readiness probes")


def no_service_account_token(a: Artifacts) -> Result:
    pods = _specs(a)
    if not pods:
        return _no_workload()
    accounts = {(d.get("metadata") or {}).get("name"): d for _, d in _facts(a).get("_docs", []) if d.get("kind") == "ServiceAccount"}
    bad = []
    for name, pod in pods:
        if pod.get("automountServiceAccountToken") is False:
            continue
        sa = accounts.get(pod.get("serviceAccountName"))
        if sa is not None and sa.get("automountServiceAccountToken") is False and pod.get("automountServiceAccountToken") is not True:
            continue
        bad.append(name)
    return ("fail", f"service account token mounted in {', '.join(bad)}") if bad else ("pass", "automountServiceAccountToken: false")


def secret_from_secret_ref(a: Artifacts) -> Result:
    var = a.spec.sections.get("kube", {}).get("secret_env")
    if not var:
        return "na", "the app needs no secret"
    items = list(_all_containers(a, include_init=False))
    if not items:
        return _no_workload()
    for n, _, c in items:
        for e in c.get("env") or []:
            if isinstance(e, dict) and e.get("name") == var:
                if "value" in e:
                    return "fail", f"{var} is a literal value in {n}"
                if ((e.get("valueFrom") or {}).get("secretKeyRef")):
                    return "pass", f"{var} from secretKeyRef"
                return "fail", f"{var} not taken from a Secret"
        for ef in c.get("envFrom") or []:
            if isinstance(ef, dict) and ef.get("secretRef"):
                return "pass", "envFrom secretRef"
    return "fail", f"{var} is not provided to the container"


def image_pinned(a: Artifacts) -> Result:
    from ..containerfile import parse_image_ref

    items = list(_all_containers(a))
    if not items:
        return _no_workload()
    bad = []
    for n, _, c in items:
        ref = parse_image_ref(str(c.get("image", "")))
        if ref.digest is None and (ref.tag is None or ref.tag == "latest"):
            bad.append(f"{n}:{c.get('image')}")
    return ("fail", f"floating image tags: {', '.join(bad)}") if bad else ("pass", "every image has a version tag or digest")


CHECKS: tuple[Check, ...] = (
    Check("pss-run-as-non-root", "security", "Set `runAsNonRoot: true` (pod or container securityContext).",
          ("pod-level securityContext", "container-level securityContext"), 1.0, False, run_as_non_root,
          title="runAsNonRoot",
          why="Pod Security Standards (restricted) require it: the kubelet then refuses to start a container that would run as root.",
          how="Every container (including init containers) resolves `runAsNonRoot: true` from its own or the pod's securityContext, "
          "and no `runAsUser: 0`."),
    Check("pss-no-privilege-escalation", "security", "Set `allowPrivilegeEscalation: false` on every container.",
          ("container securityContext",), 1.0, False, no_privilege_escalation,
          title="No privilege escalation",
          why="Blocks setuid binaries and similar from gaining more privileges than the process started with (PSS restricted).",
          how="`securityContext.allowPrivilegeEscalation: false` on every container, including init containers."),
    Check("pss-drop-all-capabilities", "security", "Drop all Linux capabilities (`capabilities.drop: [ALL]`).",
          ("drop ALL, optionally add NET_BIND_SERVICE",), 1.0, False, drop_all_capabilities,
          title="All capabilities dropped",
          why="Default container capabilities (e.g. NET_RAW, CHOWN) are rarely needed; PSS restricted requires dropping ALL.",
          how="Every container drops `ALL`; only `NET_BIND_SERVICE` may be added back."),
    Check("pss-seccomp-runtime-default", "security", "Use the `RuntimeDefault` seccomp profile.",
          ("pod-level seccompProfile", "container-level seccompProfile", "Localhost profile"), 1.0, False, seccomp_runtime_default,
          title="RuntimeDefault seccomp",
          why="Filters dangerous syscalls; required by PSS restricted, and not applied by default on many clusters.",
          how="`seccompProfile.type` is `RuntimeDefault` (or `Localhost`) at pod or container level for every container. Static: "
          "`podman kube play` ignores this field."),
    Check("read-only-root-filesystem", "security", "Run with a read-only root filesystem (writable paths as volumes).",
          ("readOnlyRootFilesystem + emptyDir for scratch paths",), 1.0, False, read_only_root_filesystem,
          title="Read-only root filesystem",
          why="An attacker who gets code execution cannot modify the application or drop tools; also enforces statelessness.",
          how="`securityContext.readOnlyRootFilesystem: true` on every app container (not part of PSS restricted, a common "
          "hardening baseline). The pod must still pass the probe under `podman kube play`, which applies it."),
    Check("resource-requests-limits", "efficiency", "Set CPU and memory requests and a memory limit.",
          ("requests + memory limit (a CPU limit is optional)",), 1.0, False, resources,
          title="Resource requests and memory limit",
          why="Requests drive scheduling; a memory limit contains leaks. Autopilot-style platforms inject defaults when missing.",
          how="Every app container has `requests.cpu`, `requests.memory` and `limits.memory`."),
    Check("health-probes", "maintainability", "Define liveness and readiness probes.",
          ("httpGet", "tcpSocket", "exec"), 1.0, False, probes,
          title="Liveness and readiness probes",
          why="Without readiness, traffic reaches pods before they can serve; without liveness, a hung process is never restarted.",
          how="Every app container defines both `livenessProbe` and `readinessProbe` (readiness is checked statically: kube play "
          "ignores it)."),
    Check("no-service-account-token", "security", "Do not mount the service account token (`automountServiceAccountToken: false`).",
          ("pod spec", "ServiceAccount used by the pod"), 1.0, False, no_service_account_token,
          title="No service account token",
          why="The app never calls the Kubernetes API; a mounted token only helps an attacker move laterally.",
          how="`automountServiceAccountToken: false` on the pod spec, or on the ServiceAccount the pod uses."),
    Check("secret-from-secret-ref", "security", "Provide secrets from a Secret (`secretKeyRef`), never as a literal env value.",
          ("env valueFrom.secretKeyRef", "envFrom secretRef"), 1.0, False, secret_from_secret_ref,
          title="Secret provided via Secret",
          why="Literal values end up in the Deployment object, its history and every `kubectl get -o yaml`.",
          how="The task's secret variable reaches the container through `valueFrom.secretKeyRef` or `envFrom.secretRef`.",
          not_applicable="The task's app needs no secret."),
    Check("image-pinned", "reproducibility", "Reference images with an explicit version tag or digest, never `latest`.",
          ("version tag", "digest"), 1.0, False, image_pinned,
          title="Images pinned",
          why="`latest` makes rollbacks and audits impossible: the same manifest can run different code tomorrow.",
          how="Every container image reference has a non-`latest` tag or a `@sha256:` digest."),
)
