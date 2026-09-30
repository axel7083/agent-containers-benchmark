"""`openshift`: the image must run under OpenShift's restricted-v2 constraints.

OpenShift runs containers with an arbitrary, unknown UID that belongs to the
root group (GID 0), with every capability dropped, no privilege escalation and
no binding to ports below 1024. The task's image gate already starts the image
that way (`[run] args` in the spec); these checks look at why it does or does
not cope.
"""

from __future__ import annotations

import json
import os
import stat

from .. import gates
from ..model import Artifacts, Check, Status

Result = tuple[Status, str]
# World-writable (sticky) scratch dirs every base image ships; not a finding.
SCRATCH_DIRS = ("tmp", "var/tmp", "dev", "run", "proc", "sys", "var/lock", "var/run", "dev/shm", "var/lib/nginx/tmp")


def collect(a: Artifacts, base_url: str, port: int, log: list[str]) -> None:
    cfg = a.spec.sections.get("openshift", {})
    facts: dict = {"port": port}
    write_path = cfg.get("write_path")
    if write_path:
        body = json.dumps(cfg.get("write_body", {"text": "acb"})).encode()
        facts["write_status"] = gates.http_request(base_url + write_path, "POST", body)
    with gates.mounted_image(log) as root:
        if root is not None:
            found = []
            for dirpath, dirnames, _ in os.walk(root):
                rel = os.path.relpath(dirpath, root)
                if rel != "." and (rel.startswith(SCRATCH_DIRS) or rel.split(os.sep)[0] in ("proc", "sys", "dev")):
                    dirnames[:] = []
                    continue
                try:
                    mode = os.lstat(dirpath).st_mode
                except OSError:
                    continue
                if mode & stat.S_IWOTH and not mode & stat.S_ISVTX and rel != ".":
                    found.append("/" + rel)
            facts["world_writable"] = sorted(found)[:20]
    a.runtime.facts["openshift"] = facts


def _facts(a: Artifacts) -> dict | None:
    return a.runtime.facts.get("openshift")


def arbitrary_uid_writes(a: Artifacts) -> Result:
    facts = _facts(a)
    if facts is None:
        return "fail", "the image did not start under an arbitrary UID"
    status = facts.get("write_status")
    if status is None:
        return "fail", "write request got no answer"
    ok = 200 <= status < 300
    return ("pass" if ok else "fail"), f"POST {a.spec.sections.get('openshift', {}).get('write_path')} as an arbitrary UID -> {status}"


def unprivileged_port(a: Artifacts) -> Result:
    ports = a.runtime.facts.get("image", {}).get("exposed_ports")
    if ports is None:
        return "fail", "image not built"
    if not ports:
        return "na", "no EXPOSE; the listening port is exercised by the gate"
    low = [p for p in ports if p < 1024]
    return ("fail", f"exposes privileged port(s) {low}") if low else ("pass", f"exposes {ports}")


def numeric_user(a: Artifacts) -> Result:
    user = a.runtime.image_user
    if user is None:
        return "fail", "image not built"
    uid = user.split(":")[0]
    if not uid:
        return "fail", "no USER (defaults to root)"
    if not uid.isdigit():
        return "fail", f"USER {user} is a name: the platform cannot verify it is non-root"
    if uid == "0":
        return "fail", "USER 0"
    return "pass", f"USER {user}"


def no_world_writable(a: Artifacts) -> Result:
    facts = _facts(a)
    if facts is None or "world_writable" not in facts:
        return "fail", "image not inspected"
    found = facts["world_writable"]
    return ("fail", f"world-writable: {', '.join(found[:5])}") if found else ("pass", "no world-writable directories outside scratch dirs")


CHECKS: tuple[Check, ...] = (
    Check(
        "arbitrary-uid-writes", "security",
        "Make the directories the application writes to owned by the root group and group-writable, so it works under an arbitrary UID.",
        ("chgrp -R 0 + chmod -R g=u", "write only under /tmp or a mounted volume"), 1.0, True, arbitrary_uid_writes,
        title="Writes work under an arbitrary UID",
        why="OpenShift's restricted SCC starts the container with a random UID that only shares the root group (GID 0) with the "
        "image. Files owned by a fixed user such as `node` or `1001` are not writable, so the app fails at its first write.",
        how="The gate runs the image with `--user 40713:0 --cap-drop=all --security-opt no-new-privileges` and unprivileged ports "
        "starting at 1024; the check then POSTs to the task's write endpoint and expects a 2xx answer.",
    ),
    Check(
        "unprivileged-port", "security", "Listen on a port above 1024.",
        ("any port >= 1024",), 1.0, True, unprivileged_port,
        title="Unprivileged port",
        why="Without the NET_BIND_SERVICE capability, which restricted SCCs drop, a process cannot bind ports below 1024.",
        how="Ports declared with `EXPOSE` in the rebuilt image.",
        not_applicable="The image declares no port.",
    ),
    Check(
        "numeric-user", "security", "Declare the runtime user as a numeric UID.",
        ("USER 1001", "USER 1001:0"), 1.0, True, numeric_user,
        title="Numeric non-root USER",
        why="Platforms enforcing runAsNonRoot can only verify a numeric UID; a user name is rejected because it could map to root.",
        how="`User` in the rebuilt image's config: a number other than 0.",
    ),
    Check(
        "no-world-writable", "security", "Do not make directories world-writable to work around permissions.",
        ("group 0 ownership with g=u",), 1.0, True, no_world_writable,
        title="No world-writable directories",
        why="`chmod 777` fixes the permission error but lets any process in the container rewrite the application.",
        how="Walks the image filesystem for directories with the other-write bit and no sticky bit, ignoring standard scratch "
        "directories (`/tmp`, `/var/tmp`, `/dev`, `/run`).",
    ),
)
