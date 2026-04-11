"""Repeated-line annotation parsing."""

from __future__ import annotations

from dataclasses import dataclass
import re

ANNOTATION_FIELDS = ("surface", "roles", "modes", "invariants", "depends_on")
DEFAULT_MODES = ("query", "edit")
SUPPORTED_MODES = set(DEFAULT_MODES)

_COMMENT_RE = re.compile(r"^\s*(?P<prefix>#|//)\s*(?P<body>.*?)\s*$")
_VALID_RE = re.compile(
    r"^(?P<field>surface|roles|modes|invariants|depends_on)\s*:\s*(?P<value>.*)$"
)
_MALFORMED_RE = re.compile(r"^(?P<field>surface|roles|modes|invariants|depends_on)\b(?!\s*:)")


@dataclass(slots=True, frozen=True)
class AnnotationCandidate:
    is_candidate: bool
    line_number: int
    field: str | None = None
    values: tuple[str, ...] = ()
    warning: str | None = None
    raw_value: str = ""


@dataclass(slots=True, frozen=True)
class AnnotationMetadata:
    surface: str
    roles: tuple[str, ...] = ()
    modes: tuple[str, ...] = DEFAULT_MODES
    invariants: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


def parse_annotation_candidate(line: str, line_number: int) -> AnnotationCandidate:
    """Parse a single comment line if it looks like annotation metadata."""

    match = _COMMENT_RE.match(line)
    if not match:
        return AnnotationCandidate(is_candidate=False, line_number=line_number)

    body = match.group("body").strip()
    if not body:
        return AnnotationCandidate(is_candidate=False, line_number=line_number)

    valid_match = _VALID_RE.match(body)
    if valid_match:
        field = valid_match.group("field")
        raw_value = valid_match.group("value").strip()
        if not raw_value:
            return AnnotationCandidate(
                is_candidate=True,
                line_number=line_number,
                field=field,
                warning=f"line {line_number}: annotation `{field}` is missing a value",
            )
        return AnnotationCandidate(
            is_candidate=True,
            line_number=line_number,
            field=field,
            values=_split_values(field, raw_value),
            raw_value=raw_value,
        )

    malformed_match = _MALFORMED_RE.match(body)
    if malformed_match:
        field = malformed_match.group("field")
        return AnnotationCandidate(
            is_candidate=True,
            line_number=line_number,
            field=field,
            warning=f"line {line_number}: malformed annotation `{field}`; expected `{field}: value`",
        )

    return AnnotationCandidate(is_candidate=False, line_number=line_number)


def finalize_annotation_run(candidates: list[AnnotationCandidate], file_display: str) -> tuple[AnnotationMetadata | None, list[str]]:
    """Convert parsed annotation lines into metadata plus warnings."""

    warnings: list[str] = []
    surface: str | None = None
    roles: list[str] = []
    modes: list[str] = []
    invariants: list[str] = []
    depends_on: list[str] = []
    saw_modes = False

    for candidate in candidates:
        if candidate.warning:
            warnings.append(f"{file_display}:{candidate.warning}")
            continue
        if candidate.field is None:
            continue
        if candidate.field == "surface":
            if surface is not None:
                warnings.append(
                    f"{file_display}:line {candidate.line_number}: duplicate `surface` field in one annotation block; last value wins"
                )
            surface = candidate.raw_value
            continue
        if candidate.field == "roles":
            roles.extend(candidate.values)
            continue
        if candidate.field == "modes":
            saw_modes = True
            invalid_modes = [mode for mode in candidate.values if mode not in SUPPORTED_MODES]
            if invalid_modes:
                warnings.append(
                    f"{file_display}:line {candidate.line_number}: unsupported modes {', '.join(invalid_modes)}"
                )
            modes.extend(mode for mode in candidate.values if mode in SUPPORTED_MODES)
            continue
        if candidate.field == "invariants":
            invariants.extend(candidate.values)
            continue
        if candidate.field == "depends_on":
            depends_on.extend(candidate.values)

    if surface is None:
        warnings.append(f"{file_display}: annotation block is missing a `surface` field and was skipped")
        return None, warnings

    unique_roles = _dedupe(roles)
    unique_modes = _dedupe(modes) if saw_modes else DEFAULT_MODES
    unique_invariants = _dedupe(invariants)
    unique_dependencies = _dedupe(depends_on)

    metadata = AnnotationMetadata(
        surface=surface,
        roles=unique_roles,
        modes=unique_modes,
        invariants=unique_invariants,
        depends_on=unique_dependencies,
    )
    return metadata, warnings


def _split_values(field: str, raw_value: str) -> tuple[str, ...]:
    if field == "surface":
        return (raw_value.strip(),)
    return tuple(chunk.strip() for chunk in raw_value.split(",") if chunk.strip())


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)
