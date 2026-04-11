"""CLI entrypoint for scoped-control."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo
from scoped_control.errors import ScopedControlError
from scoped_control.integrations.github import load_remote_edit_request
from scoped_control.tui.commands import execute_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scoped-control", description="Scoped AI control plane for repositories.")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create .scoped-control/config.yaml and index.json")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config and index")
    init_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root to initialize")

    check_parser = subparsers.add_parser("check", help="Validate config presence and schema")
    check_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    scan_parser = subparsers.add_parser("scan", help="Scan repo annotations and write .scoped-control/index.json")
    scan_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    index_parser = subparsers.add_parser("index", help="Show the stored surface index summary")
    index_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    install_parser = subparsers.add_parser("install", help="Install integration scaffolding")
    install_subparsers = install_parser.add_subparsers(dest="install_command", required=True)
    install_github_parser = install_subparsers.add_parser("github", help="Install GitHub remote-edit workflow")
    install_github_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    install_github_parser.add_argument("--workflow-path")
    install_github_parser.add_argument("--force", action="store_true")
    install_slack_parser = install_subparsers.add_parser("slack", help="Explain Slack placeholder status")
    install_slack_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    install_email_parser = install_subparsers.add_parser("email", help="Explain email placeholder status")
    install_email_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    query_parser = subparsers.add_parser("query", help="Run a read-only scoped query")
    query_parser.add_argument("role_name")
    query_parser.add_argument("request_tokens", nargs="+")
    query_parser.add_argument("--executor", choices=("codex", "claude_code", "fake"))
    query_parser.add_argument("--top-k", type=int, default=3)
    query_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    edit_parser = subparsers.add_parser("edit", help="Run a scoped edit with deterministic enforcement")
    edit_parser.add_argument("role_name")
    edit_parser.add_argument("request_tokens", nargs="+")
    edit_parser.add_argument("--executor", choices=("codex", "claude_code", "fake"))
    edit_parser.add_argument("--top-k", type=int, default=1)
    edit_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    remote_edit_parser = subparsers.add_parser("remote-edit", help="Run a remote edit from a GitHub event payload")
    remote_edit_parser.add_argument("--event-file", type=Path, required=True, help="Path to a GitHub event payload JSON file")
    remote_edit_parser.add_argument("--executor", choices=("codex", "claude_code", "fake"))
    remote_edit_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    role_parser = subparsers.add_parser("role", help="Manage roles in config.yaml")
    role_subparsers = role_parser.add_subparsers(dest="role_command", required=True)
    role_list = role_subparsers.add_parser("list", help="List configured roles")
    role_list.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    role_add = role_subparsers.add_parser("add", help="Add a new role")
    _configure_role_arguments(role_add)
    role_add.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    role_edit = role_subparsers.add_parser("edit", help="Edit an existing role")
    _configure_role_arguments(role_edit)
    role_edit.add_argument("--clear-query-paths", action="store_true")
    role_edit.add_argument("--clear-edit-paths", action="store_true")
    role_edit.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    role_remove = role_subparsers.add_parser("remove", help="Remove a role")
    role_remove.add_argument("name")
    role_remove.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    surface_parser = subparsers.add_parser("surface", help="Inspect indexed surfaces")
    surface_subparsers = surface_parser.add_subparsers(dest="surface_command", required=True)
    surface_list = surface_subparsers.add_parser("list", help="List indexed surfaces")
    surface_list.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    surface_show = surface_subparsers.add_parser("show", help="Show one indexed surface")
    surface_show.add_argument("surface_id")
    surface_show.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    validator_parser = subparsers.add_parser("validator", help="Inspect configured validators")
    validator_subparsers = validator_parser.add_subparsers(dest="validator_command", required=True)
    validator_list = validator_subparsers.add_parser("list", help="List configured validators")
    validator_list.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    tui_parser = subparsers.add_parser("tui", help="Launch the Textual console")
    tui_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return _run_init(args.path, args.force)
        if args.command == "tui":
            return _run_tui(args.path)
        if args.command == "remote-edit":
            return _run_remote_edit(args)
        if args.command in {"check", "scan", "index", "install", "query", "edit", "role", "surface", "validator"}:
            return _run_shared_command(args)
        return _run_tui(Path.cwd())
    except ScopedControlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"Error: unknown role `{exc.args[0]}`", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _run_init(path: Path, force: bool) -> int:
    paths = bootstrap_repo(path, overwrite=force)
    print(f"Initialized scoped-control in {paths.control_dir}")
    print(f"- config: {paths.config_path}")
    print(f"- index: {paths.index_path}")
    return 0


def _run_shared_command(args: argparse.Namespace) -> int:
    path = args.path
    result = execute_args(path, args)
    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    for line in result.lines:
        print(line, file=stream)
    return 0 if result.ok else 1


def _run_remote_edit(args: argparse.Namespace) -> int:
    request = load_remote_edit_request(args.event_file)
    namespace = argparse.Namespace(
        command="edit",
        role_name=request.role_name,
        request_tokens=[request.request],
        executor=args.executor or request.executor,
        top_k=request.top_k,
    )
    result = execute_args(args.path, namespace, raw_command=f"remote-edit {request.role_name}")
    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    for line in result.lines:
        print(line, file=stream)
    return 0 if result.ok else 1


def _run_tui(path: Path) -> int:
    ScopedControlApp(start_path=path).run()
    return 0


def _configure_role_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name")
    parser.add_argument("--description")
    parser.add_argument("--query-path", action="append")
    parser.add_argument("--edit-path", action="append")


if __name__ == "__main__":
    raise SystemExit(main())
