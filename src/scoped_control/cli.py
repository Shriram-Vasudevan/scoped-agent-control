"""CLI entrypoint for scoped-control."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scoped_control.app import ScopedControlApp
from scoped_control.config.loader import bootstrap_repo, check_repo
from scoped_control.errors import ScopedControlError
from scoped_control.index.builder import rebuild_index
from scoped_control.index.store import load_index, list_surfaces


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

    tui_parser = subparsers.add_parser("tui", help="Launch the Textual console")
    tui_parser.add_argument("--path", type=Path, default=Path.cwd(), help="Repo root or nested path to inspect")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return _run_init(args.path, args.force)
        if args.command == "check":
            return _run_check(args.path)
        if args.command == "scan":
            return _run_scan(args.path)
        if args.command == "index":
            return _run_index(args.path)
        if args.command == "tui":
            return _run_tui(args.path)
        return _run_tui(Path.cwd())
    except ScopedControlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _run_init(path: Path, force: bool) -> int:
    paths = bootstrap_repo(path, overwrite=force)
    print(f"Initialized scoped-control in {paths.control_dir}")
    print(f"- config: {paths.config_path}")
    print(f"- index: {paths.index_path}")
    return 0


def _run_check(path: Path) -> int:
    report = check_repo(path)
    if not report.ok:
        for error in report.errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"OK: {report.config_path}")
    return 0


def _run_scan(path: Path) -> int:
    result, index_path = rebuild_index(path)
    print(f"Indexed {len(result.index.surfaces)} surfaces from {result.files_scanned} files.")
    print(f"Wrote {index_path}")
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    return 0


def _run_index(path: Path) -> int:
    report = check_repo(path)
    if not report.ok:
        for error in report.errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    index = load_index(report.config_path.parent / "index.json")
    print(f"Index root: {index.root}")
    print(f"Surface count: {len(index.surfaces)}")
    for surface in list_surfaces(index):
        print(f"- {surface.id} @ {surface.file}:{surface.line_start}-{surface.line_end}")
    if index.warnings:
        print("Warnings:")
        for warning in index.warnings:
            print(f"- {warning}")
    return 0


def _run_tui(path: Path) -> int:
    ScopedControlApp(start_path=path).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
