"""Grader data model: task spec, check results, and the artifacts checks inspect."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from .containerfile import Containerfile

Status = Literal["pass", "fail", "na", "error"]
Category = Literal["security", "reproducibility", "efficiency", "podman-native", "maintainability"]

FAILURE_CLASSES = ("none", "no-artifact", "build", "start", "probe", "infra")


@dataclass
class Probe:
    path: str = "/"
    expect_status: int = 200
    expect_body: str | None = None


@dataclass
class Spec:
    """Contents of a task's `tests/spec.toml`."""

    family: str
    language: str
    port: int
    needs_build: bool = False
    image_size_mb: int | None = None
    canary_file: str | None = None
    canary_value: str | None = None
    probe: Probe = field(default_factory=Probe)

    @classmethod
    def load(cls, path: Path) -> "Spec":
        data = tomllib.loads(path.read_text())
        app = data.get("app", {})
        canary = data.get("canary", {})
        return cls(
            family=data["family"],
            language=app["language"],
            port=int(app["port"]),
            needs_build=bool(app.get("needs_build", False)),
            image_size_mb=data.get("budget", {}).get("image_size_mb"),
            canary_file=canary.get("file"),
            canary_value=canary.get("value"),
            probe=Probe(**data.get("probe", {})),
        )


@dataclass
class Runtime:
    """Facts gathered by the gates from the built image and running container."""

    image_size_bytes: int | None = None
    image_user: str | None = None
    image_healthcheck: bool | None = None
    process_uids: list[int] | None = None
    canary_in_filesystem: bool | None = None
    canary_in_history: bool | None = None
    hadolint: list[dict[str, Any]] | None = None


@dataclass
class Artifacts:
    app_dir: Path
    spec: Spec
    containerfile_path: Path | None = None
    containerfile: Containerfile | None = None
    runtime: Runtime = field(default_factory=Runtime)

    @property
    def context_dir(self) -> Path:
        return self.containerfile_path.parent if self.containerfile_path else self.app_dir


@dataclass
class CheckResult:
    id: str
    category: str
    weight: float
    status: Status
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Check:
    """One measurable practice.

    `rule` is phrased as an instruction and is reused verbatim in the explicit
    prompt arm, so the grader and the prompt never drift apart. `accepted`
    lists the equally valid strategies the check passes for. `title`, `why`
    and `how` document the check; the results site renders them as-is.
    """

    id: str
    category: Category
    rule: str
    accepted: tuple[str, ...]
    weight: float
    needs_runtime: bool
    evaluate: Callable[[Artifacts], tuple[Status, str]]
    title: str = ""
    why: str = ""
    how: str = ""
    not_applicable: str = ""

    def describe(self) -> dict:
        return {
            "id": self.id,
            "title": self.title or self.id,
            "category": self.category,
            "weight": self.weight,
            "rule": self.rule,
            "why": self.why,
            "how": self.how,
            "accepted": list(self.accepted),
            "not_applicable": self.not_applicable,
            "informational": self.weight == 0,
        }

    def run(self, artifacts: Artifacts) -> CheckResult:
        try:
            status, evidence = self.evaluate(artifacts)
        except Exception as exc:  # a broken check must never sink the whole grade
            status, evidence = "error", f"{type(exc).__name__}: {exc}"
        return CheckResult(self.id, self.category, self.weight, status, evidence)
