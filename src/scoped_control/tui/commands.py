"""Shared command parsing and execution for CLI and TUI flows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import shlex
from pathlib import Path

from scoped_control.annotations.inserter import auto_annotate_repo
from scoped_control.cleanup import cleanup_repo
from scoped_control.config.loader import check_repo, load_config, repo_paths
from scoped_control.config.mutator import add_role, remove_role, update_role, write_config
from scoped_control.enforcement.diff_checks import apply_file_changes, collect_file_changes, enforce_diff_limits
from scoped_control.enforcement.invariants import collect_edit_precheck_notes
from scoped_control.enforcement.span_checks import enforce_surface_spans
from scoped_control.executors.base import build_edit_executor, build_query_executor
from scoped_control.executors.sandbox import prepare_edit_workspace, prepare_query_workspace
from scoped_control.index.builder import rebuild_index
from scoped_control.index.store import get_surface, list_surfaces, load_index
from scoped_control.integrations.installer import install_github, install_slack, placeholder_install_message
from scoped_control.integrations.slack import send_slack_notification
from scoped_control.models import RoleConfig
from scoped_control.resolver.brief import compile_edit_brief, compile_query_brief, render_edit_brief, render_query_brief
from scoped_control.resolver.matcher import resolve_edit_surfaces, resolve_query_surfaces
from scoped_control.validators.runner import run_validators


class _CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


@dataclass(slots=True, frozen=True)
class CommandResult:
    command: str
    ok: bool
    message: str
    lines: tuple[str, ...] = ()
    selected_surface_id: str | None = None


def execute_command(repo_path: Path, command_text: str) -> CommandResult:
    """Execute a slash command from the Textual shell."""

    text = command_text.strip()
    if not text:
        return CommandResult(command=command_text, ok=False, message="Command input is empty.")
    if text.startswith("/"):
        text = text[1:].strip()
    if not text:
        return CommandResult(command=command_text, ok=False, message="Command input is empty.")

    try:
        args = _build_command_parser().parse_args(shlex.split(text))
    except ValueError as exc:
        return CommandResult(command=command_text, ok=False, message=f"Command parse error: {exc}")
    try:
        return execute_args(repo_path, args, raw_command=command_text)
    except Exception as exc:
        return CommandResult(command=command_text, ok=False, message=str(exc))


def execute_args(repo_path: Path, args: argparse.Namespace, *, raw_command: str | None = None) -> CommandResult:
    """Execute parsed command args from either the CLI or the TUI."""

    command_name = raw_command or _command_label(args)

    if args.command == "check":
        report = check_repo(repo_path)
        if not report.ok:
            return CommandResult(command=command_name, ok=False, message=report.errors[0], lines=report.errors)
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"OK: {report.config_path}",
            lines=(f"Repo: {report.repo_root}", f"Config: {report.config_path}"),
        )

    if args.command == "scan":
        result, index_path = rebuild_index(repo_path)
        lines = (
            f"Indexed {len(result.index.surfaces)} surfaces from {result.files_scanned} files.",
            f"Wrote {index_path}",
            *tuple(f"Warning: {warning}" for warning in result.warnings),
        )
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"Indexed {len(result.index.surfaces)} surfaces.",
            lines=lines,
        )

    if args.command == "index":
        report = check_repo(repo_path)
        if not report.ok:
            return CommandResult(command=command_name, ok=False, message=report.errors[0], lines=report.errors)
        index = load_index(repo_paths(repo_path).index_path)
        lines = (
            f"Index root: {index.root}",
            f"Surface count: {len(index.surfaces)}",
            *tuple(f"{surface.id} @ {surface.file}:{surface.line_start}-{surface.line_end}" for surface in list_surfaces(index)),
            *tuple(f"Warning: {warning}" for warning in index.warnings),
        )
        return CommandResult(command=command_name, ok=True, message=f"Loaded {len(index.surfaces)} surfaces.", lines=lines)

    if args.command == "annotate":
        return _execute_annotate_command(repo_path, args, command_name)

    if args.command == "cleanup":
        return _execute_cleanup_command(repo_path, args, command_name)

    if args.command == "query":
        return _execute_query_command(repo_path, args, command_name)

    if args.command == "edit":
        return _execute_edit_command(repo_path, args, command_name)

    if args.command == "install":
        return _execute_install_command(repo_path, args, command_name)

    if args.command == "role":
        return _execute_role_command(repo_path, args, command_name)

    if args.command == "surface":
        return _execute_surface_command(repo_path, args, command_name)

    if args.command == "validator":
        return _execute_validator_command(repo_path, args, command_name)

    return CommandResult(command=command_name, ok=False, message=f"Unsupported command: {args.command}")


def _execute_role_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    paths, config = load_config(repo_path)

    if args.role_command == "list":
        lines = tuple(
            f"{role.name}: query={_display_paths(role.query_paths)} edit={_display_paths(role.edit_paths)}"
            for role in config.roles
        ) or ("No roles configured.",)
        return CommandResult(command=command_name, ok=True, message=f"{len(config.roles)} role(s) loaded.", lines=lines)

    if args.role_command == "add":
        role = RoleConfig(
            name=args.name,
            description=args.description or "",
            query_paths=tuple(args.query_path or ()),
            edit_paths=tuple(args.edit_path or ()),
        )
        updated = add_role(config, role)
        write_config(updated, paths.config_path)
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"Added role `{role.name}`.",
            lines=(f"Query paths: {_display_paths(role.query_paths)}", f"Edit paths: {_display_paths(role.edit_paths)}"),
        )

    if args.role_command == "edit":
        current = config.get_role(args.name)
        role = RoleConfig(
            name=current.name,
            description=current.description if args.description is None else args.description,
            query_paths=current.query_paths if args.query_path is None and not args.clear_query_paths else tuple(args.query_path or ()),
            edit_paths=current.edit_paths if args.edit_path is None and not args.clear_edit_paths else tuple(args.edit_path or ()),
        )
        updated = update_role(config, role)
        write_config(updated, paths.config_path)
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"Updated role `{role.name}`.",
            lines=(f"Query paths: {_display_paths(role.query_paths)}", f"Edit paths: {_display_paths(role.edit_paths)}"),
        )

    if args.role_command == "remove":
        updated = remove_role(config, args.name)
        write_config(updated, paths.config_path)
        return CommandResult(command=command_name, ok=True, message=f"Removed role `{args.name}`.")

    return CommandResult(command=command_name, ok=False, message=f"Unsupported role command: {args.role_command}")


def _execute_annotate_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    paths, config = load_config(repo_path)
    query_globs, edit_globs = _resolve_annotation_globs(
        config,
        role_names=tuple(args.role),
        query_globs=tuple(args.query_glob or ()),
        edit_globs=tuple(args.edit_glob or ()),
    )
    if not query_globs and not edit_globs:
        return CommandResult(
            command=command_name,
            ok=False,
            message="No annotation targets resolved. Pass --query-glob/--edit-glob or configure role paths first.",
        )
    result = auto_annotate_repo(
        paths.root,
        roles=tuple(args.role),
        query_globs=query_globs,
        edit_globs=edit_globs,
        force=args.force,
        dry_run=args.dry_run,
    )
    lines = (
        f"Query globs: {_display_paths(query_globs)}",
        f"Edit globs: {_display_paths(edit_globs)}",
        f"Annotated files: {len(result.annotated_files)}",
        *tuple(f"Annotated: {item}" for item in result.annotated_files),
        *tuple(f"Skipped: {item}" for item in result.skipped_files),
        *tuple(f"Warning: {item}" for item in result.warnings),
    )
    if not args.dry_run:
        rebuild_result, _ = rebuild_index(paths.root)
        lines = (*lines, f"Reindexed surfaces: {len(rebuild_result.index.surfaces)}")
    return CommandResult(
        command=command_name,
        ok=True,
        message=f"Auto-annotated {len(result.annotated_files)} file(s).",
        lines=lines,
    )


def _execute_cleanup_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    if not args.force and not args.dry_run:
        return CommandResult(
            command=command_name,
            ok=False,
            message="Cleanup is destructive. Re-run with `cleanup --force` or preview with `cleanup --dry-run`.",
        )

    result = cleanup_repo(repo_path, dry_run=args.dry_run)
    artifact_count = len(result.annotation_files) + len(result.removed_files) + len(result.removed_directories)
    lines = (
        f"Repo: {result.root}",
        f"Annotation files: {len(result.annotation_files)}",
        f"Annotation blocks: {result.annotation_blocks_removed}",
        *tuple(f"Cleaned annotation: {path}" for path in result.annotation_files),
        *tuple(f"Removed file: {path}" for path in result.removed_files),
        *tuple(f"Removed directory: {path}" for path in result.removed_directories),
        *tuple(f"Warning: {warning}" for warning in result.warnings),
    )
    if artifact_count == 0:
        return CommandResult(command=command_name, ok=True, message="No scoped-control artifacts found.", lines=lines)
    message = "Cleanup preview complete." if args.dry_run else "Removed scoped-control artifacts."
    return CommandResult(command=command_name, ok=True, message=message, lines=lines)


def _execute_query_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    paths, config = load_config(repo_path)
    index = load_index(paths.index_path)
    role = config.get_role(args.role_name)
    request = " ".join(args.request_tokens).strip()
    resolution = resolve_query_surfaces(role, index, request, top_k=args.top_k)
    if not resolution.matches:
        return CommandResult(command=command_name, ok=False, message=f"No query surfaces matched for role `{role.name}`.")

    brief = compile_query_brief(paths.root, config, role, request, resolution.matches, resolution.dependency_surfaces)
    adapter = build_query_executor(config, args.executor)
    prompt = render_query_brief(brief)
    with prepare_query_workspace(brief) as workspace:
        result = adapter.run_query(brief, prompt, workspace)

    lines = (
        f"Executor: {adapter.name}",
        f"Allowed files: {_display_paths(brief.allowed_files)}",
        *tuple(
            f"Matched {match.surface.id}: {', '.join(match.reasons) or 'fallback within allowed query scope'}"
            for match in resolution.matches
        ),
        "Response:",
        result.output,
    )
    return CommandResult(command=command_name, ok=result.ok, message=result.summary, lines=lines)


def _execute_edit_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    paths, config = load_config(repo_path)
    index = load_index(paths.index_path)
    role = config.get_role(args.role_name)
    request = " ".join(args.request_tokens).strip()
    resolution = resolve_edit_surfaces(role, index, request, top_k=args.top_k)
    if not resolution.matches:
        return CommandResult(command=command_name, ok=False, message=f"No edit surfaces matched for role `{role.name}`.")

    brief = compile_edit_brief(paths.root, config, role, request, resolution.matches, resolution.dependency_surfaces)
    prompt = render_edit_brief(brief)
    adapter = build_edit_executor(config, args.executor)
    precheck_notes = collect_edit_precheck_notes(
        tuple(match.surface for match in resolution.matches),
        resolution.dependency_surfaces,
    )

    with prepare_edit_workspace(paths.root, resolution.writable_files) as prepared:
        result = adapter.run_edit(brief, prompt, prepared.root, resolution.writable_files)
        changes = collect_file_changes(paths.root, prepared.root)
        block_reasons = list(enforce_diff_limits(changes, config.limits))
        block_reasons.extend(
            enforce_surface_spans(
                changes,
                tuple(match.surface for match in resolution.matches),
                resolution.dependency_surfaces,
            )
        )
        validations = run_validators(config, prepared.root, mode="edit")
        block_reasons.extend(
            f"validator failed: {validation.name}"
            for validation in validations
            if not validation.ok
        )

        if block_reasons:
            lines = (
                f"Executor: {adapter.name}",
                f"Sandbox: {prepared.strategy}",
                *tuple(f"Precheck: {note}" for note in precheck_notes),
                *tuple(f"Blocked: {reason}" for reason in dict.fromkeys(block_reasons)),
                *tuple(f"Validator {validation.name}: {'ok' if validation.ok else 'failed'}" for validation in validations),
            )
            notification_status = _notify_slack_if_configured(
                config,
                command_name=command_name,
                repo_path=paths.root,
                ok=False,
                message="Edit blocked by deterministic enforcement.",
                lines=lines,
            )
            if notification_status:
                lines = (*lines, notification_status)
            return CommandResult(command=command_name, ok=False, message="Edit blocked by deterministic enforcement.", lines=lines)

        apply_file_changes(paths.root, prepared.root, changes)

    changed_files = tuple(change.path for change in changes)
    lines = (
        f"Executor: {adapter.name}",
        f"Writable files: {_display_paths(resolution.writable_files)}",
        f"Changed files: {_display_paths(changed_files)}",
        *tuple(f"Precheck: {note}" for note in precheck_notes),
        *tuple(
            f"Matched {match.surface.id}: {', '.join(match.reasons) or 'fallback within allowed edit scope'}"
            for match in resolution.matches
        ),
        *tuple(f"Validator {validation.name}: {'ok' if validation.ok else 'failed'}" for validation in validations),
        "Response:",
        result.output,
    )
    notification_status = _notify_slack_if_configured(
        config,
        command_name=command_name,
        repo_path=paths.root,
        ok=True,
        message=result.summary,
        lines=lines,
    )
    if notification_status:
        lines = (*lines, notification_status)
    return CommandResult(command=command_name, ok=True, message=result.summary, lines=lines)


def _execute_install_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    if args.install_command == "github":
        config_path, workflow_file, triage_workflow_file = install_github(
            repo_path,
            workflow_path=args.workflow_path,
            force=args.force,
        )
        return CommandResult(
            command=command_name,
            ok=True,
            message="Installed GitHub remote-edit and remote-triage scaffolding.",
            lines=(
                f"Config: {config_path}",
                f"Edit workflow: {workflow_file}",
                f"Triage workflow: {triage_workflow_file}",
                "Next: add OPENAI_API_KEY and/or ANTHROPIC_API_KEY repository secrets before running the workflows.",
            ),
        )

    if args.install_command == "claude-code":
        from scoped_control.integrations.claude_code import install_claude_code

        installed = install_claude_code(repo_path, force=args.force)
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"Installed {len(installed)} Claude Code slash command(s).",
            lines=tuple(f"Command: {path}" for path in installed),
        )

    if args.install_command == "slack":
        return CommandResult(
            command=command_name,
            ok=True,
            message="Installed Slack notification wiring.",
            lines=(
                f"Config: {install_slack(repo_path, webhook_env=args.webhook_env)}",
                f"Webhook env: {args.webhook_env}",
                "Next: set the webhook env var locally or as a GitHub Actions secret.",
            ),
        )

    if args.install_command == "email":
        return CommandResult(command=command_name, ok=True, message=placeholder_install_message(args.install_command))

    return CommandResult(command=command_name, ok=False, message=f"Unsupported install target: {args.install_command}")


def _execute_surface_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    index = load_index(repo_paths(repo_path).index_path)

    if args.surface_command == "list":
        surfaces = list_surfaces(index)
        lines = tuple(
            f"{surface.id} @ {surface.file}:{surface.line_start}-{surface.line_end}"
            for surface in surfaces
        ) or ("No indexed surfaces found. Run `scan` first.",)
        return CommandResult(command=command_name, ok=True, message=f"{len(index.surfaces)} surface(s) loaded.", lines=lines)

    if args.surface_command == "show":
        surface = get_surface(index, args.surface_id)
        if surface is None:
            return CommandResult(command=command_name, ok=False, message=f"Unknown surface `{args.surface_id}`.")
        lines = (
            f"File: {surface.file}",
            f"Span: {surface.line_start}-{surface.line_end}",
            f"Roles: {_display_paths(surface.roles)}",
            f"Modes: {_display_paths(surface.modes)}",
            f"Invariants: {_display_paths(surface.invariants)}",
            f"Depends on: {_display_paths(surface.depends_on)}",
            f"Hash: {surface.hash}",
        )
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"Showing surface `{surface.id}`.",
            lines=lines,
            selected_surface_id=surface.id,
        )

    return CommandResult(command=command_name, ok=False, message=f"Unsupported surface command: {args.surface_command}")


def _execute_validator_command(repo_path: Path, args: argparse.Namespace, command_name: str) -> CommandResult:
    _, config = load_config(repo_path)
    if args.validator_command == "list":
        lines = tuple(
            f"{validator.name}: {validator.command} [{', '.join(validator.modes)}]"
            for validator in config.validators
        ) or ("No validators configured.",)
        return CommandResult(
            command=command_name,
            ok=True,
            message=f"{len(config.validators)} validator(s) loaded.",
            lines=lines,
        )
    return CommandResult(command=command_name, ok=False, message=f"Unsupported validator command: {args.validator_command}")


def _build_command_parser() -> _CommandParser:
    parser = _CommandParser(prog="/", add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", add_help=False)
    subparsers.add_parser("scan", add_help=False)
    subparsers.add_parser("index", add_help=False)
    cleanup_parser = subparsers.add_parser("cleanup", add_help=False)
    cleanup_parser.add_argument("--dry-run", action="store_true")
    cleanup_parser.add_argument("--force", action="store_true")
    annotate_parser = subparsers.add_parser("annotate", add_help=False)
    annotate_parser.add_argument("--role", action="append", required=True)
    annotate_parser.add_argument("--query-glob", action="append")
    annotate_parser.add_argument("--edit-glob", action="append")
    annotate_parser.add_argument("--force", action="store_true")
    annotate_parser.add_argument("--dry-run", action="store_true")
    install_parser = subparsers.add_parser("install", add_help=False)
    install_commands = install_parser.add_subparsers(dest="install_command", required=True)
    install_github_parser = install_commands.add_parser("github", add_help=False)
    install_github_parser.add_argument("--workflow-path")
    install_github_parser.add_argument("--force", action="store_true")
    install_slack_parser = install_commands.add_parser("slack", add_help=False)
    install_slack_parser.add_argument("--webhook-env", default="SLACK_WEBHOOK_URL")
    install_commands.add_parser("email", add_help=False)
    install_claude_parser = install_commands.add_parser("claude-code", add_help=False)
    install_claude_parser.add_argument("--force", action="store_true")
    query_parser = subparsers.add_parser("query", add_help=False)
    query_parser.add_argument("role_name")
    query_parser.add_argument("request_tokens", nargs="+")
    query_parser.add_argument("--executor", choices=("codex", "claude_code", "fake"))
    query_parser.add_argument("--top-k", type=int, default=3)
    edit_parser = subparsers.add_parser("edit", add_help=False)
    edit_parser.add_argument("role_name")
    edit_parser.add_argument("request_tokens", nargs="+")
    edit_parser.add_argument("--executor", choices=("codex", "claude_code", "fake"))
    edit_parser.add_argument("--top-k", type=int, default=1)

    role_parser = subparsers.add_parser("role", add_help=False)
    role_commands = role_parser.add_subparsers(dest="role_command", required=True)
    role_commands.add_parser("list", add_help=False)

    role_add = role_commands.add_parser("add", add_help=False)
    _configure_role_arguments(role_add, require_name=True)

    role_edit = role_commands.add_parser("edit", add_help=False)
    _configure_role_arguments(role_edit, require_name=True)
    role_edit.add_argument("--clear-query-paths", action="store_true")
    role_edit.add_argument("--clear-edit-paths", action="store_true")

    role_remove = role_commands.add_parser("remove", add_help=False)
    role_remove.add_argument("name")

    surface_parser = subparsers.add_parser("surface", add_help=False)
    surface_commands = surface_parser.add_subparsers(dest="surface_command", required=True)
    surface_commands.add_parser("list", add_help=False)
    surface_show = surface_commands.add_parser("show", add_help=False)
    surface_show.add_argument("surface_id")

    validator_parser = subparsers.add_parser("validator", add_help=False)
    validator_commands = validator_parser.add_subparsers(dest="validator_command", required=True)
    validator_commands.add_parser("list", add_help=False)

    return parser


def _configure_role_arguments(parser: argparse.ArgumentParser, *, require_name: bool) -> None:
    if require_name:
        parser.add_argument("name")
    parser.add_argument("--description")
    parser.add_argument("--query-path", action="append")
    parser.add_argument("--edit-path", action="append")


def _display_paths(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "<none>"


def _resolve_annotation_globs(config, *, role_names: tuple[str, ...], query_globs: tuple[str, ...], edit_globs: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if query_globs or edit_globs:
        return query_globs, edit_globs

    resolved_query: list[str] = []
    resolved_edit: list[str] = []
    for role_name in role_names:
        role = config.get_role(role_name)
        resolved_query.extend(role.query_paths)
        resolved_edit.extend(role.edit_paths)
    return tuple(dict.fromkeys(resolved_query)), tuple(dict.fromkeys(resolved_edit))


def _command_label(args: argparse.Namespace) -> str:
    if args.command in {"check", "scan", "index", "cleanup"}:
        return args.command
    if args.command == "annotate":
        return "annotate"
    if args.command == "install":
        return f"install {args.install_command}"
    if args.command == "query":
        return f"query {args.role_name}"
    if args.command == "edit":
        return f"edit {args.role_name}"
    if args.command == "role":
        return f"role {args.role_command}"
    if args.command == "surface":
        return f"surface {args.surface_command}"
    if args.command == "validator":
        return f"validator {args.validator_command}"
    return str(args.command)


def _notify_slack_if_configured(
    config,
    *,
    command_name: str,
    repo_path: Path,
    ok: bool,
    message: str,
    lines: tuple[str, ...],
) -> str | None:
    if command_name.startswith("remote-edit"):
        event_key = "remote_edit_success" if ok else "remote_edit_blocked"
    else:
        event_key = "edit_success" if ok else "edit_blocked"
    try:
        return send_slack_notification(
            config,
            event_key=event_key,
            repo_root=repo_path,
            command=command_name,
            ok=ok,
            message=message,
            lines=lines,
        )
    except Exception as exc:
        return f"Slack notification failed: {exc}"
