"""Practice checks for the `containerfile` family.

Every check states its rule once (reused in the explicit prompt arm) and the
strategies it accepts. Checks return `na` when the practice does not apply to
the task (e.g. multi-stage for an app with no build step) so they never
penalise a correct choice.
"""

from __future__ import annotations

import re

from .containerfile import Stage
from .model import Artifacts, Check, Status

Result = tuple[Status, str]

_PKG_INSTALL = re.compile(r"\b(dnf|microdnf|yum|apt-get|apt|apk)\b[^&;|]*\b(install|add)\b")
_PKG_CLEAN = re.compile(
    r"(dnf|microdnf|yum)\s+clean\s+all|rm\s+-rf\s+/var/lib/apt/lists|apk\s+add\s+[^&;|]*--no-cache"
    r"|--mount=type=cache|rm\s+-rf\s+/var/cache/(dnf|yum|apk)"
)
_WEIGHT_INFO = 0.0


def _cf(a: Artifacts):
    if a.containerfile is None or not a.containerfile.stages:
        return None
    return a.containerfile


def _no_file() -> Result:
    return "fail", "no Containerfile/Dockerfile found"


def containerfile_name(a: Artifacts) -> Result:
    if a.containerfile_path is None:
        return _no_file()
    name = a.containerfile_path.name
    return ("pass" if name.lower().startswith("containerfile") else "fail"), name


def fq_image_names(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    images = cf.external_images()
    if not images:
        return "na", "no external base image"
    short = [i.raw for i in images if not i.fully_qualified]
    return ("fail", f"short names: {', '.join(short)}") if short else ("pass", ", ".join(i.raw for i in images))


def base_tag_pinned(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    images = cf.external_images()
    if not images:
        return "na", "no external base image"
    floating = [i.raw for i in images if i.digest is None and (i.tag is None or i.tag == "latest")]
    return ("fail", f"floating: {', '.join(floating)}") if floating else ("pass", "all bases have a version tag or digest")


def base_digest_pinned(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    images = cf.external_images()
    if not images:
        return "na", "no external base image"
    unpinned = [i.raw for i in images if i.digest is None]
    return ("fail", f"not digest-pinned: {', '.join(unpinned)}") if unpinned else ("pass", "all bases pinned by digest")


def _is_build_toolchain_stage(stage: Stage) -> bool:
    return bool(stage.find("RUN"))


def multi_stage(a: Artifacts) -> Result:
    if not a.spec.needs_build:
        return "na", "app has no build step"
    cf = _cf(a)
    if cf is None:
        return _no_file()
    final = cf.final_stage
    if len(cf.stages) < 2:
        return "fail", "single stage"
    copies_from_stage = [c for c in final.find("COPY") if "from" in c.flags()]
    if final.base_stage is not None and _is_build_toolchain_stage(final.base_stage):
        return "fail", "final stage derives from the build stage"
    if not copies_from_stage:
        return "fail", "final stage does not COPY --from a build stage"
    return "pass", f"{len(cf.stages)} stages, final copies build output"


def final_image_size(a: Artifacts) -> Result:
    if a.spec.image_size_mb is None:
        return "na", "no size budget"
    size = a.runtime.image_size_bytes
    if size is None:
        return "fail", "image not built"
    mb = size / 1_000_000
    ok = mb <= a.spec.image_size_mb
    return ("pass" if ok else "fail"), f"{mb:.0f} MB (budget {a.spec.image_size_mb} MB)"


def non_root_user(a: Artifacts) -> Result:
    uids = a.runtime.process_uids
    if uids:
        root = [u for u in uids if u == 0]
        return ("fail", "process runs as uid 0") if root else ("pass", f"process uids {sorted(set(uids))}")
    user = a.runtime.image_user
    if user is None:
        return "fail", "image not built"
    if user in ("", "root", "0", "0:0", "root:root"):
        return "fail", f"image USER={user or '(unset)'}"
    return "pass", f"image USER={user}"


def no_secret_in_image(a: Artifacts) -> Result:
    if a.spec.canary_value is None:
        return "na", "task has no planted secret"
    fs, hist = a.runtime.canary_in_filesystem, a.runtime.canary_in_history
    if fs is None and hist is None:
        return "fail", "image not built"
    if fs or hist:
        where = [w for w, hit in (("filesystem", fs), ("history", hist)) if hit]
        return "fail", f"secret from {a.spec.canary_file} found in image {' and '.join(where)}"
    return "pass", "planted secret not in image"


def ignore_file(a: Artifacts) -> Result:
    if a.containerfile_path is None:
        return _no_file()
    for name in (".containerignore", ".dockerignore"):
        f = a.context_dir / name
        if f.is_file() and f.read_text(errors="replace").strip():
            patterns = [p.strip() for p in f.read_text(errors="replace").splitlines() if p.strip() and not p.startswith("#")]
            return "pass", f"{name}: {', '.join(patterns[:8])}"
    return "fail", "no .containerignore/.dockerignore in build context"


def deterministic_deps(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    runs = " ; ".join(i.args for i in cf.instructions if i.keyword == "RUN")
    lang = a.spec.language
    if lang == "node":
        if (a.app_dir / "package-lock.json").exists():
            if re.search(r"\bnpm\s+ci\b", runs):
                return "pass", "npm ci"
            if re.search(r"\bnpm\s+(install|i)\b", runs):
                return "fail", "npm install ignores the lockfile contract; use npm ci"
            return "na", "no npm install step"
        return "na", "no package-lock.json"
    if lang == "python":
        if re.search(r"pip3?\s+install\b[^;&|]*-r\s+\S*requirements", runs) or re.search(r"\b(uv\s+sync|poetry\s+install|pipenv\s+install)", runs):
            return "pass", "installs from the pinned requirements"
        if re.search(r"pip3?\s+install\b", runs):
            return "fail", "pip install without the pinned requirements file"
        return "na", "no pip install step"
    return "na", f"not applicable to {lang}"


def exec_form_entrypoint(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    final = cf.final_stage
    cmds = final.find("CMD") + final.find("ENTRYPOINT")
    if not cmds:
        return "na", "inherits CMD/ENTRYPOINT from base image"
    shell = [f"{c.keyword} {c.args}" for c in cmds if not c.is_exec_form]
    return ("fail", f"shell form: {'; '.join(shell)}") if shell else ("pass", "exec form")


def layer_cache_order(a: Artifacts) -> Result:
    lang = a.spec.language
    manifests = {"node": ("package.json", "package-lock.json"), "python": ("requirements.txt", "pyproject.toml"), "go": ("go.mod", "go.sum")}
    if lang not in manifests:
        return "na", f"not applicable to {lang}"
    cf = _cf(a)
    if cf is None:
        return _no_file()
    for stage in cf.stages:
        seq = [i for i in stage.instructions if i.keyword in ("COPY", "ADD", "RUN")]
        full_copy = next((n for n, i in enumerate(seq) if i.keyword in ("COPY", "ADD") and "from" not in i.flags()
                          and i.positional()[:-1] and any(src in (".", "./", "*") for src in i.positional()[:-1])), None)
        install = next((n for n, i in enumerate(seq) if i.keyword == "RUN" and re.search(r"npm\s+(ci|install|i)\b|pip3?\s+install|go\s+mod\s+download|uv\s+sync", i.args)), None)
        if install is None:
            continue
        if full_copy is None or full_copy > install:
            return "pass", "dependency install happens before copying the full source"
        return "fail", "full source copied before installing dependencies (cache busts on every change)"
    return "na", "no dependency install step"


def pkg_cache_cleaned(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    final = cf.final_stage
    installs = [r for r in final.find("RUN") if _PKG_INSTALL.search(r.args)]
    if not installs:
        return "na", "no OS package install in the final stage"
    dirty = [r.line for r in installs if not _PKG_CLEAN.search(r.args)]
    return ("fail", f"package cache left behind (lines {dirty})") if dirty else ("pass", "package cache cleaned in the same layer")


def healthcheck(a: Artifacts) -> Result:
    cf = _cf(a)
    if cf is None:
        return _no_file()
    hc = cf.final_stage.find("HEALTHCHECK")
    if not hc or hc[-1].args.upper().startswith("NONE"):
        return "fail", "no HEALTHCHECK"
    note = "" if a.runtime.image_healthcheck else " (dropped: OCI image format ignores HEALTHCHECK, needs --format docker)"
    return "pass", f"HEALTHCHECK {hc[-1].args[:60]}{note}"


def hadolint_clean(a: Artifacts) -> Result:
    findings = a.runtime.hadolint
    if findings is None:
        return _no_file() if a.containerfile_path is None else ("error", "hadolint did not run")
    bad = [f for f in findings if f.get("level") in ("error", "warning")]
    if not bad:
        return "pass", "no warnings"
    codes = sorted({f.get("code", "?") for f in bad})
    return "fail", f"{len(bad)} findings: {', '.join(codes)}"


CONTAINERFILE_CHECKS: tuple[Check, ...] = (
    Check("containerfile-name", "podman-native", "Name the build file `Containerfile`.", ("Containerfile",), _WEIGHT_INFO, False, containerfile_name),
    Check("fq-image-names", "podman-native", "Use fully qualified image names (registry/namespace/name) for every base image.", ("registry-qualified reference",), 1.0, False, fq_image_names),
    Check("base-tag-pinned", "reproducibility", "Pin base images to an explicit version tag or digest, never `latest` or an implicit tag.", ("version tag", "digest"), 1.0, False, base_tag_pinned),
    Check("base-digest-pinned", "reproducibility", "Pin base images by `@sha256:` digest.", ("digest",), 1.0, False, base_digest_pinned),
    Check("multi-stage", "efficiency", "Use a multi-stage build so build tools do not ship in the final image.", ("builder stage + COPY --from into a clean runtime base",), 1.0, False, multi_stage),
    Check("final-image-size", "efficiency", "Keep the final image small (minimal or distroless runtime base).", ("any base within the task's size budget",), 1.0, True, final_image_size),
    Check("non-root-user", "security", "Run the application as a non-root user.", ("USER with a non-zero uid", "base image whose default user is non-root"), 1.0, True, non_root_user),
    Check("no-secret-in-image", "security", "Never copy secrets such as `.env` files into the image.", ("ignore file", "explicit COPY of only the needed files"), 1.0, True, no_secret_in_image),
    Check("ignore-file", "security", "Add a `.containerignore` (or `.dockerignore`) to keep secrets, VCS data and local dependencies out of the build context.", (".containerignore", ".dockerignore"), 1.0, False, ignore_file),
    Check("deterministic-deps", "reproducibility", "Install dependencies from the lockfile (`npm ci`, `pip install -r requirements.txt`).", ("npm ci", "pip install -r", "uv sync", "poetry install"), 1.0, False, deterministic_deps),
    Check("exec-form-entrypoint", "maintainability", "Use the exec (JSON) form for CMD/ENTRYPOINT so signals reach the application.", ("exec form",), 1.0, False, exec_form_entrypoint),
    Check("layer-cache-order", "efficiency", "Copy dependency manifests and install dependencies before copying the rest of the source.", ("manifest COPY before source COPY",), 1.0, False, layer_cache_order),
    Check("pkg-cache-cleaned", "efficiency", "Clean the OS package manager cache in the same layer that installs packages.", ("dnf clean all", "rm -rf /var/lib/apt/lists/*", "apk --no-cache", "cache mounts"), 0.5, False, pkg_cache_cleaned),
    Check("healthcheck", "maintainability", "Declare a HEALTHCHECK for the service.", ("HEALTHCHECK instruction",), 0.5, False, healthcheck),
    Check("hadolint-clean", "maintainability", "Keep the Containerfile free of hadolint warnings and errors.", ("no hadolint warning/error",), 1.0, True, hadolint_clean),
)

CHECKS_BY_FAMILY: dict[str, tuple[Check, ...]] = {"containerfile": CONTAINERFILE_CHECKS}
