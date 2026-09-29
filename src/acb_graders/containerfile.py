"""Minimal Containerfile/Dockerfile parser.

Good enough to reason about stages, base images and instructions. It handles
line continuations, comments, parser directives, `ARG` substitution in `FROM`
and heredocs; it does not try to be a full BuildKit frontend.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_HEREDOC = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


@dataclass
class Instruction:
    keyword: str  # upper-cased, e.g. "RUN"
    args: str  # raw arguments, continuations joined with a space
    line: int  # 1-based line of the instruction start

    @property
    def is_exec_form(self) -> bool:
        try:
            value = json.loads(self.args)
        except ValueError:
            return False
        return isinstance(value, list) and all(isinstance(v, str) for v in value)

    def flags(self) -> dict[str, str]:
        """Leading `--flag=value` options (e.g. COPY --from=builder)."""
        out: dict[str, str] = {}
        for token in self.args.split():
            if not token.startswith("--"):
                break
            name, _, value = token[2:].partition("=")
            out[name] = value
        return out

    def positional(self) -> list[str]:
        tokens = self.args.split()
        while tokens and tokens[0].startswith("--"):
            tokens.pop(0)
        return tokens


@dataclass
class ImageRef:
    raw: str
    registry: str | None
    repository: str
    tag: str | None
    digest: str | None

    @property
    def fully_qualified(self) -> bool:
        return self.registry is not None

    @property
    def is_scratch(self) -> bool:
        return self.raw == "scratch"


@dataclass
class Stage:
    index: int
    base: str  # FROM argument after ARG substitution
    name: str | None
    instructions: list[Instruction] = field(default_factory=list)
    base_stage: "Stage | None" = None  # when FROM refers to a previous stage

    @property
    def image(self) -> ImageRef | None:
        """External base image, or None for `scratch` / stage references."""
        if self.base_stage is not None or self.base == "scratch":
            return None
        return parse_image_ref(self.base)

    def find(self, keyword: str) -> list[Instruction]:
        return [i for i in self.instructions if i.keyword == keyword]


@dataclass
class Containerfile:
    path: Path
    instructions: list[Instruction]
    stages: list[Stage]
    global_args: dict[str, str]

    @property
    def final_stage(self) -> Stage | None:
        return self.stages[-1] if self.stages else None

    def external_images(self) -> list[ImageRef]:
        return [s.image for s in self.stages if s.image is not None]

    def root_image(self, stage: Stage) -> ImageRef | None:
        """External image a stage ultimately derives from (following stage refs)."""
        seen = set()
        while stage.base_stage is not None and stage.index not in seen:
            seen.add(stage.index)
            stage = stage.base_stage
        return stage.image


def parse_image_ref(ref: str) -> ImageRef:
    raw = ref
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    tag = None
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        ref, tag = ref.rsplit(":", 1)
    parts = ref.split("/")
    registry = None
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        parts = parts[1:]
    return ImageRef(raw=raw, registry=registry, repository="/".join(parts), tag=tag, digest=digest)


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join continuation lines, drop comments, fold heredoc bodies into the instruction."""
    escape = "\\"
    lines = text.splitlines()
    # Parser directive `# escape=` may only appear before any instruction.
    for raw in lines:
        stripped = raw.strip()
        if not stripped.startswith("#"):
            break
        m = re.match(r"#\s*escape\s*=\s*(\S)", stripped, re.IGNORECASE)
        if m:
            escape = m.group(1)

    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    heredoc_end: list[str] = []
    for lineno, raw in enumerate(lines, start=1):
        if heredoc_end:
            buf.append(raw)
            if raw.strip() == heredoc_end[0]:
                heredoc_end.pop(0)
                if not heredoc_end:
                    out.append((start, "\n".join(buf)))
                    buf = []
            continue
        stripped = raw.strip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if buf and stripped.startswith("#"):
            continue  # comment inside a continuation
        if not buf:
            start = lineno
        if stripped.endswith(escape):
            buf.append(stripped[: -len(escape)].rstrip())
            continue
        buf.append(stripped)
        joined = " ".join(b for b in buf if b)
        markers = _HEREDOC.findall(joined) if joined.split(None, 1)[0].upper() in ("RUN", "COPY") else []
        if markers:
            heredoc_end = list(markers)
            buf = [joined]
            continue
        out.append((start, joined))
        buf = []
    if buf:
        out.append((start, " ".join(buf)))
    return out


def _substitute(value: str, variables: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(3)
        default = m.group(2)
        if name in variables and variables[name] != "":
            return variables[name]
        return default if default is not None else ""

    return _VAR.sub(repl, value)


def parse(text: str, path: Path | str = "Containerfile") -> Containerfile:
    instructions: list[Instruction] = []
    for lineno, line in _logical_lines(text):
        keyword, _, args = line.partition(" ")
        instructions.append(Instruction(keyword=keyword.upper(), args=args.strip(), line=lineno))

    global_args: dict[str, str] = {}
    stages: list[Stage] = []
    by_name: dict[str, Stage] = {}
    for ins in instructions:
        if ins.keyword == "ARG" and not stages:
            for token in ins.positional():
                name, _, default = token.partition("=")
                global_args[name] = default.strip("\"'")
            continue
        if ins.keyword == "FROM":
            tokens = ins.positional()
            base = _substitute(tokens[0], global_args) if tokens else ""
            name = tokens[2] if len(tokens) >= 3 and tokens[1].upper() == "AS" else None
            stage = Stage(index=len(stages), base=base, name=name)
            ref = by_name.get(base.lower())
            if ref is None and base.isdigit() and int(base) < len(stages):
                ref = stages[int(base)]
            stage.base_stage = ref
            stages.append(stage)
            if name:
                by_name[name.lower()] = stage
            continue
        if stages:
            stages[-1].instructions.append(ins)
    return Containerfile(path=Path(path), instructions=instructions, stages=stages, global_args=global_args)


def parse_file(path: Path) -> Containerfile:
    return parse(path.read_text(errors="replace"), path)
