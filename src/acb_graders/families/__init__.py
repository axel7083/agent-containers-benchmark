"""Check families beyond the Containerfile ones, and their runtime hooks."""

from __future__ import annotations

from . import bots, cloudrun, kube, openshift, quadlet

FAMILY_CHECKS = {
    "update-bots": bots.CHECKS,
    "openshift": openshift.CHECKS,
    "cloudrun": cloudrun.CHECKS,
    "kube": kube.CHECKS,
    "quadlet": quadlet.CHECKS,
}

# Called by the image gate once the container answers its probe: (artifacts, base_url, port, log).
RUNTIME_HOOKS = {
    "openshift": openshift.collect,
    "cloudrun": cloudrun.collect,
}
