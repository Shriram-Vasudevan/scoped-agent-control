"""Shared command parsing and execution for CLI and TUI flows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import shlex
from pathlib import Path

from scoped_control.config.loader import check_repo, load_config, repo_paths
from scoped_control.config.mutator import add_role, remove_role, update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.index.store import get_surface, list_surfaces, load_index
from scoped_control.models import RoleConfig


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


def _command_label(args: argparse.Namespace) -> str:
    if args.command in {"check", "scan", "index"}:
        return args.command
    if args.command == "role":
        return f"role {args.role_command}"
    if args.command == "surface":
        return f"surface {args.surface_command}"
    if args.command == "validator":
        return f"validator {args.validator_command}"
    return str(args.command)
