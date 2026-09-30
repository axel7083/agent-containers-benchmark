"""`update-bots`: the repository's dependency-update bot must also cover the Containerfile.

The starting repo already has Dependabot or Renovate configured for the app's
language only. When the agent adds a Containerfile, the base images it pins
will go stale unless the bot is taught to watch them.

Grading is static: Dependabot has no offline runner, and Renovate's own
extraction needs network presets, so both are evaluated from the config the
way the bots resolve it (documented behaviour, see `how` of each check).
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from ..model import Artifacts, Check, Status

Result = tuple[Status, str]

DEPENDABOT_FILES = (".github/dependabot.yml", ".github/dependabot.yaml")
RENOVATE_FILES = ("renovate.json", ".github/renovate.json", ".gitlab/renovate.json", ".renovaterc", ".renovaterc.json")
# Renovate's dockerfile manager default managerFilePatterns (docs.renovatebot.com/modules/manager/dockerfile/).
RENOVATE_DOCKERFILE_DEFAULT = (
    re.compile(r"(^|/|\.)([Dd]ocker|[Cc]ontainer)file$"),
    re.compile(r"(^|/)([Dd]ocker|[Cc]ontainer)file[^/]*$"),
)


def glob_match(path: str, pattern: str) -> bool:
    """minimatch-style glob: `**/` spans zero or more directories, `*` stays inside one."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.fullmatch(out, path) is not None


def _kind(a: Artifacts) -> str:
    return a.spec.sections.get("bots", {}).get("kind", "dependabot")


def _containerfile_rel(a: Artifacts) -> str | None:
    if a.containerfile_path is None:
        return None
    return a.containerfile_path.relative_to(a.app_dir).as_posix()


def _load_dependabot(app: Path) -> tuple[dict | None, str]:
    import yaml

    for name in DEPENDABOT_FILES:
        f = app / name
        if f.is_file():
            try:
                data = yaml.safe_load(f.read_text())
            except yaml.YAMLError as exc:
                return None, f"{name}: invalid YAML ({exc.__class__.__name__})"
            return (data if isinstance(data, dict) else None), name
    return None, "no .github/dependabot.yml"


def _load_renovate(app: Path) -> tuple[dict | None, str]:
    for name in RENOVATE_FILES:
        f = app / name
        if f.is_file():
            try:
                data = json.loads(f.read_text())
            except ValueError:
                return None, f"{name}: invalid JSON"
            return (data if isinstance(data, dict) else None), name
    pkg = app / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text()).get("renovate")
            if isinstance(data, dict):
                return data, "package.json#renovate"
        except ValueError:
            pass
    return None, "no Renovate config"


def _dependabot_dir_matches(entry: dict, rel_dir: str) -> bool:
    target = "/" + rel_dir.strip("/") if rel_dir not in ("", ".") else "/"
    dirs = []
    if isinstance(entry.get("directory"), str):
        dirs.append(entry["directory"])
    if isinstance(entry.get("directories"), list):
        dirs += [d for d in entry["directories"] if isinstance(d, str)]
    for d in dirs:
        norm = "/" + d.strip().strip("/") if d.strip() not in ("", "/") else "/"
        if norm == target or glob_match(target, norm) or (norm.endswith("/**") and target.startswith(norm[:-3])):
            return True
    return False


def _renovate_covers(cfg: dict, rel_file: str) -> Result:
    enabled = cfg.get("enabledManagers")
    if isinstance(enabled, list) and enabled and "dockerfile" not in enabled:
        return "fail", f"enabledManagers {enabled} excludes the dockerfile manager"
    dockerfile_cfg = cfg.get("dockerfile") if isinstance(cfg.get("dockerfile"), dict) else {}
    if dockerfile_cfg.get("enabled") is False:
        return "fail", "dockerfile manager disabled"
    for pattern in cfg.get("ignorePaths") or []:
        # Renovate ignores a file when its path contains the entry or matches it as a minimatch glob.
        if isinstance(pattern, str) and (pattern in rel_file or glob_match(rel_file, pattern)):
            return "fail", f"{rel_file} is excluded by ignorePaths {pattern!r}"
    for rule in cfg.get("packageRules") or []:
        if isinstance(rule, dict) and rule.get("enabled") is False and "dockerfile" in (rule.get("matchManagers") or []) \
                and not rule.get("matchPackageNames") and not rule.get("matchDepNames"):
            return "fail", "a packageRule disables the dockerfile manager"
    patterns = dockerfile_cfg.get("managerFilePatterns") or dockerfile_cfg.get("fileMatch")
    if patterns:
        for p in patterns:
            p = str(p)
            rx = p[1:-1] if p.startswith("/") and p.endswith("/") and len(p) > 1 else None
            if (rx and re.search(rx, rel_file)) or (not rx and glob_match(rel_file, p)):
                return "pass", f"dockerfile manager patterns {patterns} match {rel_file}"
        # Custom patterns extend the defaults in current Renovate; fall through to the defaults.
    if any(rx.search(rel_file) for rx in RENOVATE_DOCKERFILE_DEFAULT):
        return "pass", f"dockerfile manager (default patterns) covers {rel_file}"
    return "fail", f"no dockerfile manager pattern matches {rel_file}"


def bot_covers_containerfile(a: Artifacts) -> Result:
    rel = _containerfile_rel(a)
    if rel is None:
        return "fail", "no Containerfile/Dockerfile found"
    if _kind(a) == "dependabot":
        data, where = _load_dependabot(a.app_dir)
        if data is None:
            return "fail", where
        docker = [u for u in data.get("updates") or [] if isinstance(u, dict) and u.get("package-ecosystem") == "docker"]
        if not docker:
            return "fail", f"{where}: no `docker` package-ecosystem entry"
        rel_dir = str(PurePosixPath(rel).parent)
        if any(_dependabot_dir_matches(u, rel_dir) for u in docker):
            return "pass", f"{where}: docker ecosystem covers /{rel_dir if rel_dir != '.' else ''}"
        return "fail", f"{where}: docker entries do not cover the directory of {rel}"
    data, where = _load_renovate(a.app_dir)
    if data is None:
        return "fail", where
    status, evidence = _renovate_covers(data, rel)
    return status, f"{where}: {evidence}"


def bot_keeps_existing(a: Artifacts) -> Result:
    existing = a.spec.sections.get("bots", {}).get("existing", [])
    if not existing:
        return "na", "nothing configured before"
    if _kind(a) == "dependabot":
        data, where = _load_dependabot(a.app_dir)
        if data is None:
            return "fail", where
        have = {u.get("package-ecosystem") for u in data.get("updates") or [] if isinstance(u, dict)}
        missing = [e for e in existing if e not in have]
        return ("fail", f"{where}: dropped {missing}") if missing else ("pass", f"{where}: still updates {existing}")
    data, where = _load_renovate(a.app_dir)
    if data is None:
        return "fail", where
    enabled = data.get("enabledManagers")
    if isinstance(enabled, list) and enabled:
        missing = [e for e in existing if e not in enabled]
        return ("fail", f"{where}: enabledManagers dropped {missing}") if missing else ("pass", f"{where}: keeps {existing}")
    return "pass", f"{where}: all managers enabled"


def bot_config_valid(a: Artifacts) -> Result:
    if _kind(a) == "dependabot":
        data, where = _load_dependabot(a.app_dir)
        if data is None:
            return "fail", where
        if data.get("version") != 2:
            return "fail", f"{where}: version must be 2"
        problems = []
        for i, u in enumerate(data.get("updates") or []):
            if not isinstance(u, dict):
                problems.append(f"updates[{i}] is not a mapping")
                continue
            if not u.get("package-ecosystem"):
                problems.append(f"updates[{i}] has no package-ecosystem")
            if not (u.get("directory") or u.get("directories")):
                problems.append(f"updates[{i}] has no directory/directories")
            if not (isinstance(u.get("schedule"), dict) and u["schedule"].get("interval")):
                problems.append(f"updates[{i}] has no schedule.interval")
        return ("fail", f"{where}: {'; '.join(problems)}") if problems else ("pass", f"{where}: well-formed")
    data, where = _load_renovate(a.app_dir)
    if data is None:
        return "fail", where
    return "pass", f"{where}: parses as a JSON object"


CHECKS: tuple[Check, ...] = (
    Check(
        "bot-covers-containerfile", "reproducibility",
        "Keep base images updated: extend the repository's dependency-update bot (Dependabot or Renovate) to cover the Containerfile.",
        ("Dependabot `docker` entry covering its directory", "Renovate dockerfile manager enabled and not ignored"), 1.0, False,
        bot_covers_containerfile,
        title="Update bot covers the Containerfile",
        why="Pinned base images only stay secure if something proposes updates. A repository that already runs Dependabot or "
        "Renovate for its app dependencies should get the same treatment for its images.",
        how="Dependabot: an `updates` entry with `package-ecosystem: docker` whose `directory` (or a `directories` glob) is the "
        "Containerfile's directory; Dependabot detects files named `Containerfile` as well as `Dockerfile`. Renovate: the "
        "`dockerfile` manager is enabled, not excluded by `enabledManagers`, `ignorePaths` or a disabling `packageRule`, and its "
        "file patterns (default: `Dockerfile`/`Containerfile` names) match the file.",
    ),
    Check(
        "bot-keeps-existing", "maintainability", "Keep the dependency updates that were already configured.",
        ("existing ecosystems/managers retained",), 1.0, False, bot_keeps_existing,
        title="Existing update config kept",
        why="Adding container coverage must not silently drop the application dependency updates the team relied on.",
        how="Every ecosystem (Dependabot) or manager (Renovate `enabledManagers`) configured in the starting repository is still present.",
        not_applicable="The task starts with no update configuration.",
    ),
    Check(
        "bot-config-valid", "maintainability", "Keep the update bot configuration valid.",
        ("well-formed config",), 1.0, False, bot_config_valid,
        title="Update bot config is valid",
        why="An invalid config makes the bot stop working entirely, usually without anyone noticing.",
        how="Dependabot: YAML with `version: 2`, and every update has `package-ecosystem`, `directory`/`directories` and "
        "`schedule.interval`. Renovate: the config file parses as a JSON object.",
    ),
)
