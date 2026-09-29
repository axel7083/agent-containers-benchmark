"""Prompt arms rendered from the check catalogue.

`explicit` lists every scored rule of a family verbatim, `nudge` is a single
generic sentence. Keeping them generated from `checks.py` guarantees the
explicit arm asks for exactly what the graders measure.
"""

from __future__ import annotations

from .checks import CHECKS_BY_FAMILY

ARMS = ("implicit", "nudge", "explicit")

NUDGE = "Follow container best practices (security, reproducibility, image size) in your solution."


def render(arm: str, family: str) -> str:
    if arm == "implicit":
        return ""
    if arm == "nudge":
        return NUDGE + "\n"
    if arm == "explicit":
        lines = ["Follow these container best practices:"]
        lines += [f"- {c.rule}" for c in CHECKS_BY_FAMILY[family] if c.weight > 0]
        return "\n".join(lines) + "\n"
    raise ValueError(f"unknown arm {arm!r}")
