"""Execution brief compilation for query runs."""

from __future__ import annotations

from pathlib import Path

from scoped_control.models import AppConfig, ExecutionBrief, FileContext, ResolverMatch, RoleConfig, SurfaceRecord


def compile_query_brief(
    root: Path,
    config: AppConfig,
    role: RoleConfig,
    request: str,
    matches: tuple[ResolverMatch, ...],
    dependency_surfaces: tuple[SurfaceRecord, ...],
) -> ExecutionBrief:
    """Compile a compact execution brief with only the scoped context."""

    file_contexts: list[FileContext] = []
    for match in matches:
        file_contexts.append(_surface_context(root, match.surface, kind="target"))
    for surface in dependency_surfaces:
        file_contexts.append(_surface_context(root, surface, kind="dependency"))

    invariants = tuple(
        dict.fromkeys(invariant for match in matches for invariant in match.surface.invariants)
    )
    query_validators = tuple(validator.name for validator in config.validators if "query" in validator.modes)
    notes = tuple(
        f"{match.surface.id}: {', '.join(match.reasons) or 'fallback within allowed query scope'}"
        for match in matches
    )
    dependency_files = tuple(sorted({surface.file for surface in dependency_surfaces}))
    allowed_files = tuple(sorted({context.path for context in file_contexts}))

    return ExecutionBrief(
        kind="query",
        role_name=role.name,
        request=request,
        allowed_files=allowed_files,
        target_surfaces=tuple(match.surface for match in matches),
        dependency_files=dependency_files,
        invariants=invariants,
        validators=query_validators,
        notes=notes,
        file_contexts=tuple(file_contexts),
    )


def render_query_brief(brief: ExecutionBrief) -> str:
    """Render a brief as a compact prompt for external executors."""

    lines: list[str] = [
        "You are answering a scoped repository query.",
        "Use only the provided context excerpts.",
        "Do not assume access to any other files or repository history.",
        "",
        f"Role: {brief.role_name}",
        f"Request: {brief.request}",
        "",
        "Allowed files:",
        *[f"- {path}" for path in brief.allowed_files],
        "",
        "Target surfaces:",
        *[
            f"- {surface.id} ({surface.file}:{surface.line_start}-{surface.line_end})"
            for surface in brief.target_surfaces
        ],
    ]

    if brief.invariants:
        lines.extend(["", "Invariants:", *[f"- {item}" for item in brief.invariants]])
    if brief.dependency_files:
        lines.extend(["", "Dependency hint files:", *[f"- {item}" for item in brief.dependency_files]])
    if brief.validators:
        lines.extend(["", "Relevant validators:", *[f"- {item}" for item in brief.validators]])
    if brief.notes:
        lines.extend(["", "Why these surfaces matched:", *[f"- {item}" for item in brief.notes]])

    for context in brief.file_contexts:
        lines.extend(
            [
                "",
                f"### {context.kind.upper()} {context.path}:{context.line_start}-{context.line_end}",
                context.excerpt,
            ]
        )

    lines.extend(
        [
            "",
            "Answer the user's question directly. If the scoped context is insufficient, say so explicitly.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def compile_edit_brief(
    root: Path,
    config: AppConfig,
    role: RoleConfig,
    request: str,
    matches: tuple[ResolverMatch, ...],
    dependency_surfaces: tuple[SurfaceRecord, ...],
) -> ExecutionBrief:
    """Compile a scoped edit brief."""

    file_contexts: list[FileContext] = []
    for match in matches:
        file_contexts.append(_surface_context(root, match.surface, kind="target"))
    for surface in dependency_surfaces:
        file_contexts.append(_surface_context(root, surface, kind="dependency"))

    invariants = tuple(dict.fromkeys(invariant for match in matches for invariant in match.surface.invariants))
    edit_validators = tuple(validator.name for validator in config.validators if "edit" in validator.modes)
    notes = tuple(
        f"{match.surface.id}: {', '.join(match.reasons) or 'fallback within allowed edit scope'}"
        for match in matches
    )
    writable_files = tuple(sorted({match.surface.file for match in matches}))
    dependency_files = tuple(sorted({surface.file for surface in dependency_surfaces}))

    return ExecutionBrief(
        kind="edit",
        role_name=role.name,
        request=request,
        allowed_files=writable_files,
        target_surfaces=tuple(match.surface for match in matches),
        dependency_files=dependency_files,
        invariants=invariants,
        validators=edit_validators,
        notes=notes,
        file_contexts=tuple(file_contexts),
    )


def render_edit_brief(brief: ExecutionBrief) -> str:
    """Render an edit brief as a compact prompt."""

    lines: list[str] = [
        "You are making a scoped repository edit inside a sandbox workspace.",
        "Modify only the writable files listed below.",
        "Stay within the target surface spans described in the context excerpts.",
        "Treat dependency excerpts as read-only context.",
        "",
        f"Role: {brief.role_name}",
        f"Request: {brief.request}",
        "",
        "Writable files:",
        *[f"- {path}" for path in brief.allowed_files],
        "",
        "Target surfaces:",
        *[
            f"- {surface.id} ({surface.file}:{surface.line_start}-{surface.line_end})"
            for surface in brief.target_surfaces
        ],
    ]

    if brief.dependency_files:
        lines.extend(["", "Dependency hint files:", *[f"- {item}" for item in brief.dependency_files]])
    if brief.invariants:
        lines.extend(["", "Invariants:", *[f"- {item}" for item in brief.invariants]])
    if brief.validators:
        lines.extend(["", "Validators that will run after the edit:", *[f"- {item}" for item in brief.validators]])
    if brief.notes:
        lines.extend(["", "Why these surfaces matched:", *[f"- {item}" for item in brief.notes]])

    for context in brief.file_contexts:
        lines.extend(
            [
                "",
                f"### {context.kind.upper()} {context.path}:{context.line_start}-{context.line_end}",
                context.excerpt,
            ]
        )

    lines.extend(["", "Make the smallest change that satisfies the request, then stop."])
    return "\n".join(lines).strip() + "\n"


def _surface_context(root: Path, surface: SurfaceRecord, *, kind: str) -> FileContext:
    file_path = root / surface.file
    lines = file_path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(lines[surface.line_start - 1 : surface.line_end])
    return FileContext(
        path=surface.file,
        kind=kind,
        excerpt=excerpt,
        line_start=surface.line_start,
        line_end=surface.line_end,
        surface_ids=(surface.id,),
    )
