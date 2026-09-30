"""`quadlet`: run the application as a systemd service with Podman Quadlet.

The gate runs Podman's Quadlet generator in dry-run mode over the agent's
units (the same code path systemd uses at boot). Checks are static on the
unit files; they accept every Quadlet unit kind (.container, .kube, .pod).
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import gates
from ..containerfile import parse_image_ref
from ..gates import GateResult
from ..model import Artifacts, Check, Status

Result = tuple[Status, str]
UNIT_SUFFIXES = (".container", ".pod", ".kube", ".volume", ".network", ".image", ".build")
MAIN_SUFFIXES = (".container", ".kube", ".pod")
QUADLET = "/usr/libexec/podman/quadlet"


def parse_unit(text: str) -> dict[str, list[tuple[str, str]]]:
    """systemd-style INI: section -> [(key, value)], keeping repeated keys and continuation lines."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        pending = ""
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
        elif "=" in line and current is not None:
            key, _, value = line.partition("=")
            sections[current].append((key.strip(), value.strip()))
    return sections


def values(unit: dict, section: str, key: str) -> list[str]:
    return [v for k, v in unit.get(section, []) if k == key]


def find_units(app: Path) -> list[Path]:
    return sorted(
        p for p in app.rglob("*")
        if p.is_file() and p.suffix in UNIT_SUFFIXES and "node_modules" not in p.parts and ".git" not in p.parts
    )


def _units(a: Artifacts) -> list[tuple[Path, dict]]:
    return a.runtime.facts.get("quadlet", {}).get("_units", [])


def _main_units(a: Artifacts) -> list[tuple[Path, dict]]:
    return [(p, u) for p, u in _units(a) if p.suffix in MAIN_SUFFIXES]


def run_gates(a: Artifacts) -> GateResult:
    res = GateResult()
    paths = find_units(a.app_dir)
    units = [(p, parse_unit(p.read_text(errors="replace"))) for p in paths]
    a.runtime.facts["quadlet"] = {"_units": units, "files": [p.relative_to(a.app_dir).as_posix() for p in paths]}
    if not any(p.suffix in MAIN_SUFFIXES for p in paths):
        return res.fail("artifact", "no-artifact")
    res.gates["artifact"] = True
    dirs = sorted({str(p.parent) for p in paths})
    env = {**os.environ, "QUADLET_UNIT_DIRS": ":".join(dirs)}
    proc = gates.run([QUADLET, "-dryrun"], log=res.log, env=env)
    ok = proc.returncode == 0 and "error" not in proc.stderr.lower()
    res.gates["validate"] = ok
    if not ok:
        res.failure_class = "validate"
    return res


def _no_units() -> Result:
    return "fail", "no Quadlet .container/.kube/.pod unit"


def starts_at_boot(a: Artifacts) -> Result:
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        targets = " ".join(values(u, "Install", "WantedBy") + values(u, "Install", "RequiredBy"))
        if "multi-user.target" in targets or "default.target" in targets:
            return "pass", f"{p.name}: WantedBy={targets}"
    return "fail", "no unit has [Install] WantedBy=multi-user.target or default.target"


def restarts(a: Artifacts) -> Result:
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        policy = values(u, "Service", "Restart")
        if policy and policy[-1] not in ("no",):
            return "pass", f"{p.name}: Restart={policy[-1]}"
    return "fail", "no [Service] Restart= policy"


def auto_update(a: Artifacts) -> Result:
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        section = {".container": "Container", ".kube": "Kube", ".pod": "Pod"}[p.suffix]
        policy = values(u, section, "AutoUpdate") + [
            v.split("=", 1)[1] for v in values(u, section, "Label") if v.startswith("io.containers.autoupdate=")
        ]
        if "registry" in policy:
            images = values(u, "Container", "Image")
            if p.suffix == ".container" and images and not images[-1].endswith((".image", ".build")):
                ref = parse_image_ref(images[-1])
                if not ref.fully_qualified:
                    return "fail", f"{p.name}: AutoUpdate=registry needs a fully qualified Image= (got {images[-1]})"
            return "pass", f"{p.name}: AutoUpdate=registry"
    return "fail", "no unit enables AutoUpdate=registry"


def persistent_data(a: Artifacts) -> Result:
    target = a.spec.sections.get("quadlet", {}).get("data_dir")
    if not target:
        return "na", "the app keeps no data"
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        for v in values(u, "Container", "Volume"):
            parts = v.split(":")
            if len(parts) >= 2 and parts[1].rstrip("/") == target.rstrip("/"):
                source, opts = parts[0], (parts[2] if len(parts) > 2 else "")
                if source.startswith(("/", "%h", "%S", "%t")) and not any(o in ("Z", "z") for o in opts.split(",")):
                    return "fail", f"{p.name}: bind mount {v} without :Z/:z (SELinux denies access)"
                return "pass", f"{p.name}: Volume={v}"
        if p.suffix == ".kube":
            return "na", f"{p.name}: volumes come from the Kubernetes YAML"
    return "fail", f"nothing persists {target}"


def secret_not_plaintext(a: Artifacts) -> Result:
    var = a.spec.sections.get("quadlet", {}).get("secret_env")
    if not var:
        return "na", "the app needs no secret"
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        for v in values(u, "Container", "Environment"):
            if v.strip('"').startswith(f"{var}="):
                return "fail", f"{p.name}: {var} as a plaintext Environment="
        for v in values(u, "Container", "Secret"):
            if f"target={var}" in v or v.split(",")[0].upper().replace("-", "_") == var:
                return "pass", f"{p.name}: Secret={v}"
        if values(u, "Container", "EnvironmentFile") or values(u, "Service", "EnvironmentFile"):
            return "pass", f"{p.name}: EnvironmentFile="
        if p.suffix == ".kube":
            return "pass", f"{p.name}: secrets come from the Kubernetes YAML"
    return "fail", f"{var} is not provided (Secret= or EnvironmentFile=)"


def healthcheck(a: Artifacts) -> Result:
    mains = _main_units(a)
    if not mains:
        return _no_units()
    for p, u in mains:
        if values(u, "Container", "HealthCmd"):
            return "pass", f"{p.name}: HealthCmd={values(u, 'Container', 'HealthCmd')[-1][:60]}"
        if p.suffix == ".kube":
            return "na", f"{p.name}: probes come from the Kubernetes YAML"
    return "fail", "no HealthCmd="


CHECKS: tuple[Check, ...] = (
    Check("starts-at-boot", "maintainability", "Enable the service at boot (`[Install] WantedBy=`).",
          ("multi-user.target", "default.target (user services)"), 1.0, False, starts_at_boot,
          title="Starts at boot",
          why="Quadlet units are generated at boot; without an [Install] section nothing starts them.",
          how="A .container/.kube/.pod unit has `WantedBy=` (or `RequiredBy=`) `multi-user.target` or `default.target`."),
    Check("restarts-on-failure", "maintainability", "Restart the service when it fails (`[Service] Restart=`).",
          ("Restart=on-failure", "Restart=always"), 1.0, False, restarts,
          title="Restarts on failure",
          why="A crashed container otherwise stays down until someone notices.",
          how="`Restart=` other than `no` in the unit's [Service] section."),
    Check("auto-update", "podman-native", "Enable Podman auto-update (`AutoUpdate=registry`) with a fully qualified image.",
          ("AutoUpdate=registry", "Label=io.containers.autoupdate=registry"), 1.0, False, auto_update,
          title="Podman auto-update",
          why="`podman auto-update` (with its systemd timer) pulls new images and restarts units, rolling back if they fail; it "
          "only considers units that opt in and reference a fully qualified image.",
          how="`AutoUpdate=registry` (or the equivalent label) in a .container/.kube/.pod unit; for .container, `Image=` must be "
          "fully qualified."),
    Check("persistent-data", "podman-native", "Keep application data on a volume (bind mounts need `:Z` on SELinux hosts).",
          ("named volume or .volume unit", "bind mount with :Z/:z"), 1.0, False, persistent_data,
          title="Data persisted correctly",
          why="The container is recreated on every restart or update; data must live outside it, and on Fedora/RHEL a bind mount "
          "without an SELinux relabel option is unreadable by the container.",
          how="A `Volume=` targets the app's data directory; a host-path source must carry `Z` or `z`.",
          not_applicable="The app keeps no data."),
    Check("secret-not-plaintext", "security", "Pass secrets with `Secret=` (podman secret) or an EnvironmentFile, not `Environment=`.",
          ("Secret=", "EnvironmentFile="), 1.0, False, secret_not_plaintext,
          title="Secret not in plaintext",
          why="Unit files are world-readable under /etc; `Environment=` also shows up in `systemctl show`.",
          how="The app's secret variable is provided with `Secret=` or an `EnvironmentFile=`, never `Environment=`.",
          not_applicable="The app needs no secret."),
    Check("healthcheck", "maintainability", "Declare a health check (`HealthCmd=`).",
          ("HealthCmd=",), 0.5, False, healthcheck,
          title="Health check",
          why="Podman runs it on a timer and, with `HealthOnFailure=`, can restart an unhealthy service.",
          how="`HealthCmd=` in a .container unit."),
)
