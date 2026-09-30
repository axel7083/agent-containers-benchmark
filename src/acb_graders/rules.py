"""Prompt arms rendered from the check catalogue.

`explicit` lists every scored rule of a family verbatim, `nudge` is a single
generic sentence. Keeping them generated from `checks.py` guarantees the
explicit arm asks for exactly what the graders measure.
"""

from __future__ import annotations

from .checks import CHECKS_BY_FAMILY

ARMS = ("implicit", "nudge", "explicit")

ARM_INFO: dict[str, dict[str, str]] = {
    "implicit": {
        "summary": "The task's natural request, nothing appended. No practice is named.",
        "reading": "Baseline behaviour: what the agent does unprompted.",
    },
    "nudge": {
        "summary": "One generic sentence appended, naming no specific practice.",
        "reading": "Gain over implicit = disposition: the model knows the practice but only applies it when reminded.",
    },
    "explicit": {
        "summary": "Every graded rule appended verbatim.",
        "reading": "Gain over nudge = missing specific knowledge. Still failing here = the model cannot do it even when told.",
    },
}

NUDGE = "Follow container best practices (security, reproducibility, image size) in your solution."


def render(arm: str, families: str | list[str] | tuple[str, ...]) -> str:
    """Text appended to a task's instruction; `families` are the check families the task is graded on."""
    if isinstance(families, str):
        families = [families]
    if arm == "implicit":
        return ""
    if arm == "nudge":
        return NUDGE + "\n"
    if arm == "explicit":
        lines = ["Follow these container best practices:"]
        lines += [f"- {c.rule}" for family in families for c in CHECKS_BY_FAMILY[family] if c.weight > 0]
        return "\n".join(lines) + "\n"
    raise ValueError(f"unknown arm {arm!r}")
