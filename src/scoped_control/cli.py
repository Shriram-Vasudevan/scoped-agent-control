"""CLI entrypoint for scoped-control."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo
from scoped_control.errors import ScopedControlError
from scoped_control.integrations.github import load_remote_edit_request
from scoped_control.setup_flow import run_setup
from scoped_control.tui.commands import execute_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scoped-control",
        description="CLI-first control plane for scoped AI query/edit operations.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create .scoped-control/config.yaml and index.json")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config and index")
    init_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root to initialize")

    setup_parser = subparsers.add_parser("setup", help="Guided repo bootstrap, role config, and auto-annotation")
    setup_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    setup_parser.add_argument("--role", help="Role name to create or update")
    setup_parser.add_argument("--description", help="Role description")
    setup_parser.add_argument("--intent", help="Plain-English description of what this role should generally be able to do")
    setup_parser.add_argument("--query-path", action="append", help="Repo path glob this role may read")
    setup_parser.add_argument("--edit-path", action="append", help="Repo path glob this role may edit")
    setup_parser.add_argument("--annotate-query-glob", action="append", help="File glob to auto-annotate for query access")
    setup_parser.add_argument("--annotate-edit-glob", action="append", help="File glob to auto-annotate for edit access")
    setup_parser.add_argument(
        "--planner-executor",
        choices=("auto", "heuristic", "codex", "claude_code"),
        default="auto",
        help="Planner used when inferring scope from --intent",
    )
    setup_parser.add_argument("--skip-annotate", action="store_true", help="Skip automatic annotation insertion")
    setup_parser.add_argument("--force-annotations", action="store_true", help="Replace detected file annotations when auto-annotating")
    setup_parser.add_argument("--install-github", action="store_true", help="Install the GitHub Actions remote-edit workflow")
    setup_parser.add_argument("--install-slack", action="store_true", help="Enable Slack notifications in config")
    setup_parser.add_argument("--slack-webhook-env", default="SLACK_WEBHOOK_URL", help="Environment variable that stores the Slack webhook URL")

    check_parser = subparsers.add_parser("check", help="Validate config presence and schema")
    check_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    scan_parser = subparsers.add_parser("scan", help="Scan repo annotations and write .scoped-control/index.json")
    scan_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    index_parser = subparsers.add_parser("index", help="Show the stored surface index summary")
    index_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove scoped-control-managed annotations and repo artifacts")
    cleanup_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Preview what would be removed")
    cleanup_parser.add_argument("--force", action="store_true", help="Apply the destructive cleanup")

    annotate_parser = subparsers.add_parser("annotate", help="Auto-insert file-level annotations from role paths or explicit globs")
    annotate_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    annotate_parser.add_argument("--role", action="append", required=True, help="Role name to stamp into generated annotations")
    annotate_parser.add_argument("--query-glob", action="append", help="File glob to annotate with query mode")
    annotate_parser.add_argument("--edit-glob", action="append", help="File glob to annotate with edit mode")
    annotate_parser.add_argument("--force", action="store_true", help="Replace detected file annotations")
    annotate_parser.add_argument("--dry-run", action="store_true", help="Report matched files without modifying them")

    install_parser = subparsers.add_parser("install", help="Install integration scaffolding")
    install_subparsers = install_parser.add_subparsers(dest="install_command", required=True)
    install_github_parser = install_subparsers.add_parser("github", help="Install GitHub remote-edit workflow")
    install_github_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    install_github_parser.add_argument("--workflow-path")
    install_github_parser.add_argument("--force", action="store_true")
    install_slack_parser = install_subparsers.add_parser("slack", help="Enable Slack notifications and wire the GitHub workflow env")
    install_slack_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    install_slack_parser.add_argument("--webhook-env", default="SLACK_WEBHOOK_URL")
    install_email_parser = install_subparsers.add_parser("email", help="Show current email integration status")
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
        if args.command is None:
            return _run_tui(Path.cwd())
        if args.command == "init":
            return _run_init(args.path, args.force)
        if args.command == "setup":
            return _run_setup(args)
        if args.command == "tui":
            return _run_tui(args.path)
        if args.command == "remote-edit":
            return _run_remote_edit(args)
        if args.command in {"check", "scan", "index", "cleanup", "annotate", "install", "query", "edit", "role", "surface", "validator"}:
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


def _run_setup(args: argparse.Namespace) -> int:
    guided = _stdin_isatty() and (
        args.role is None or args.description is None or (args.intent is None and args.query_path is None and args.edit_path is None)
    )

    role_name = args.role or _prompt_text("Role name", "maintainer", enabled=guided)
    description_default = f"Scoped operator for {args.path.resolve().name}."
    description = args.description or _prompt_text("Role description", description_default, enabled=guided)
    intent = args.intent or ""

    query_paths = tuple(args.query_path or ())
    edit_paths = tuple(args.edit_path or ())
    using_explicit_paths = bool(query_paths or edit_paths)
    if not using_explicit_paths:
        intent_default = f"{role_name} should be able to work on the relevant parts of this project."
        intent = intent or _prompt_text(
            "What should this role generally be allowed to do?",
            intent_default,
            enabled=guided,
        )

    auto_annotate_enabled = not args.skip_annotate
    if guided and not args.skip_annotate:
        auto_annotate_enabled = _prompt_bool("Auto-insert file annotations now?", True)

    annotate_query_globs = tuple(args.annotate_query_glob or query_paths)
    annotate_edit_globs = tuple(args.annotate_edit_glob or edit_paths)
    if guided and auto_annotate_enabled and using_explicit_paths:
        if args.annotate_query_glob is None:
            annotate_query_globs = _prompt_list(
                "Query files to annotate (defaults to query paths)",
                annotate_query_globs,
                enabled=True,
            )
        if args.annotate_edit_glob is None:
            annotate_edit_globs = _prompt_list(
                "Editable files to annotate (defaults to edit paths)",
                annotate_edit_globs,
                enabled=True,
            )

    force_annotations = args.force_annotations
    if guided and auto_annotate_enabled and not args.force_annotations:
        force_annotations = _prompt_bool("Replace existing file annotations when found?", False)

    install_github_enabled = args.install_github
    if guided and not args.install_github:
        install_github_enabled = _prompt_bool("Install the GitHub Actions workflow?", False)

    install_slack_enabled = args.install_slack
    if guided and not args.install_slack:
        install_slack_enabled = _prompt_bool("Enable Slack notifications?", False)

    slack_webhook_env = args.slack_webhook_env
    if guided and install_slack_enabled and args.slack_webhook_env == "SLACK_WEBHOOK_URL":
        slack_webhook_env = _prompt_text("Slack webhook env var", args.slack_webhook_env, enabled=True)

    lines = run_setup(
        args.path,
        role_name=role_name,
        description=description,
        intent=intent or None,
        query_paths=query_paths,
        edit_paths=edit_paths,
        annotate_query_globs=annotate_query_globs if auto_annotate_enabled else (),
        annotate_edit_globs=annotate_edit_globs if auto_annotate_enabled else (),
        planner_executor=args.planner_executor,
        auto_annotate_enabled=auto_annotate_enabled,
        install_github_enabled=install_github_enabled,
        install_slack_enabled=install_slack_enabled,
        slack_webhook_env=slack_webhook_env,
        force_annotations=force_annotations,
    )
    print("Setup complete.")
    for line in lines:
        print(line)
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


def _prompt_text(label: str, default: str, *, enabled: bool) -> str:
    if not enabled:
        return default
    response = input(f"{label} [{default}]: ").strip()
    return response or default


def _prompt_list(label: str, default: tuple[str, ...], *, enabled: bool) -> tuple[str, ...]:
    if not enabled:
        return default
    default_display = ", ".join(default)
    response = input(f"{label} [{default_display}]: ").strip()
    if not response:
        return default
    return tuple(part.strip() for part in response.split(",") if part.strip())


def _prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        response = input(f"{label} [{suffix}]: ").strip().lower()
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("Enter yes or no.")


def _stdin_isatty() -> bool:
    return sys.stdin.isatty()


if __name__ == "__main__":
    raise SystemExit(main())
