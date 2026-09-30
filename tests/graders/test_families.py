import json
from pathlib import Path

from acb_graders.checks import pkg_cache_cleaned
from acb_graders.containerfile import parse
from acb_graders.families import bots, kube, quadlet
from acb_graders.model import Artifacts, Spec


def artifacts(tmp_path: Path, families: list[str], **sections) -> Artifacts:
    spec = Spec(gate="image", families=families, language="node", port=8080, sections=sections)
    return Artifacts(app_dir=tmp_path, spec=spec)


def test_pkg_cache_follows_inherited_stages(tmp_path):
    a = artifacts(tmp_path, ["containerfile"])
    a.containerfile_path = tmp_path / "Containerfile"
    a.containerfile = parse("FROM quay.io/fedora/fedora:45 AS base\nRUN dnf -y install curl\nFROM base\nCMD [\"curl\"]\n")
    assert pkg_cache_cleaned(a)[0] == "fail"  # the dirty layer ships through `FROM base`
    a.containerfile = parse("FROM quay.io/fedora/fedora:45 AS build\nRUN dnf -y install gcc\nFROM scratch\nCOPY --from=build /x /x\n")
    assert pkg_cache_cleaned(a)[0] == "na"  # a builder stage that is only copied from does not ship


def test_dependabot_coverage(tmp_path):
    a = artifacts(tmp_path, ["update-bots"], bots={"kind": "dependabot", "existing": ["npm"]})
    (tmp_path / "deploy").mkdir()
    a.containerfile_path = tmp_path / "deploy" / "Containerfile"
    a.containerfile_path.write_text("FROM scratch\n")
    gh = tmp_path / ".github"
    gh.mkdir()
    (gh / "dependabot.yml").write_text(
        'version: 2\nupdates:\n  - package-ecosystem: npm\n    directory: "/"\n    schedule: {interval: weekly}\n'
        '  - package-ecosystem: docker\n    directory: "/"\n    schedule: {interval: weekly}\n'
    )
    assert bots.bot_covers_containerfile(a)[0] == "fail"  # docker entry watches "/", the file is in /deploy
    assert bots.bot_keeps_existing(a)[0] == "pass" and bots.bot_config_valid(a)[0] == "pass"
    (gh / "dependabot.yml").write_text(
        'version: 2\nupdates:\n  - package-ecosystem: docker\n    directories: ["/deploy"]\n    schedule: {interval: weekly}\n'
    )
    assert bots.bot_covers_containerfile(a)[0] == "pass"
    assert bots.bot_keeps_existing(a)[0] == "fail"  # npm was dropped


def test_renovate_coverage(tmp_path):
    a = artifacts(tmp_path, ["update-bots"], bots={"kind": "renovate", "existing": ["npm"]})
    a.containerfile_path = tmp_path / "Containerfile"
    a.containerfile_path.write_text("FROM scratch\n")
    cfg = tmp_path / "renovate.json"
    cfg.write_text(json.dumps({"enabledManagers": ["npm"]}))
    assert bots.bot_covers_containerfile(a)[0] == "fail"
    cfg.write_text(json.dumps({"enabledManagers": ["npm", "dockerfile"], "ignorePaths": ["**/Containerfile"]}))
    assert bots.bot_covers_containerfile(a)[0] == "fail"
    cfg.write_text(json.dumps({"extends": ["config:recommended"]}))
    assert bots.bot_covers_containerfile(a)[0] == "pass" and bots.bot_keeps_existing(a)[0] == "pass"


def kube_artifacts(tmp_path, pod: dict) -> Artifacts:
    a = artifacts(tmp_path, ["kube"], kube={"secret_env": "DB_PASSWORD"})
    a.runtime.facts["kube"] = {"_pods": [("Pod/x", pod)], "_docs": []}
    return a


def test_kube_pod_level_security_context_is_accepted(tmp_path):
    container = {"name": "c", "image": "quay.io/a/b:1.0", "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}}
    a = kube_artifacts(tmp_path, {"securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}}, "containers": [container]})
    assert kube.run_as_non_root(a)[0] == "pass" and kube.seccomp_runtime_default(a)[0] == "pass"
    assert kube.no_privilege_escalation(a)[0] == "pass" and kube.drop_all_capabilities(a)[0] == "pass"
    assert kube.image_pinned(a)[0] == "pass" and kube.read_only_root_filesystem(a)[0] == "fail"


def test_kube_literal_secret_and_root_are_rejected(tmp_path):
    container = {"name": "c", "image": "quay.io/a/b", "env": [{"name": "DB_PASSWORD", "value": "x"}],
                 "securityContext": {"runAsUser": 0, "capabilities": {"drop": ["ALL"], "add": ["SYS_ADMIN"]}}}
    a = kube_artifacts(tmp_path, {"securityContext": {"runAsNonRoot": True}, "containers": [container]})
    assert kube.run_as_non_root(a)[0] == "fail" and kube.drop_all_capabilities(a)[0] == "fail"
    assert kube.secret_from_secret_ref(a)[0] == "fail" and kube.image_pinned(a)[0] == "fail"


def test_quadlet_unit_parsing_and_checks(tmp_path):
    unit = quadlet.parse_unit(
        "[Container]\nImage=quay.io/acme/notes:1\nAutoUpdate=registry\nVolume=/srv/notes:/var/lib/notes\n"
        "Environment=DB_PASSWORD=x\n[Service]\nRestart=always\n[Install]\nWantedBy=default.target\n"
    )
    a = artifacts(tmp_path, ["quadlet"], quadlet={"data_dir": "/var/lib/notes", "secret_env": "DB_PASSWORD"})
    a.runtime.facts["quadlet"] = {"_units": [(tmp_path / "notes.container", unit)]}
    assert quadlet.starts_at_boot(a)[0] == "pass" and quadlet.restarts(a)[0] == "pass" and quadlet.auto_update(a)[0] == "pass"
    assert quadlet.persistent_data(a)[0] == "fail"  # host path without :Z
    assert quadlet.secret_not_plaintext(a)[0] == "fail" and quadlet.healthcheck(a)[0] == "fail"
