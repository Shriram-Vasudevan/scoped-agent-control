"""Install Claude Code slash commands for scoped-control."""

from __future__ import annotations

from pathlib import Path


COMMANDS: dict[str, str] = {
    "sc-setup.md": (
        "---\n"
        "description: Guided scoped-control repo setup with read/write intent\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "Run the scoped-control guided setup for this repository.\n\n"
        "Ask the user, one prompt at a time:\n"
        "1. Role name\n"
        "2. Role description\n"
        "3. What should this role be allowed to READ (plain English)\n"
        "4. What should this role be allowed to WRITE / EDIT (plain English, or 'none')\n\n"
        "Then run:\n\n"
        "```bash\n"
        "scoped-control setup --path . \\\n"
        "  --role <role> \\\n"
        "  --description <description> \\\n"
        "  --read-intent <read intent> \\\n"
        "  --write-intent <write intent>\n"
        "```\n\n"
        "Show the Planner reasoning, Query paths, and Edit paths back to the user and ask them to confirm.\n"
    ),
    "sc-triage.md": (
        "---\n"
        "description: Triage a natural-language request into a scoped query or edit\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "Triage `$ARGUMENTS` and show the decision. Do not run it unless the user confirms.\n\n"
        "```bash\n"
        "scoped-control triage $ARGUMENTS --path .\n"
        "```\n\n"
        "Report back: mode, role, target files, and the reason. If it is blocked, explain why.\n"
        "If the user confirms, re-run with `--execute` added.\n"
    ),
    "sc-query.md": (
        "---\n"
        "description: Run a scoped read-only query through scoped-control\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "Run a scoped-control query. Expect `$ARGUMENTS` to begin with a role name followed by the request.\n\n"
        "```bash\n"
        "scoped-control query $ARGUMENTS --path .\n"
        "```\n"
    ),
    "sc-edit.md": (
        "---\n"
        "description: Run a scoped edit through scoped-control (deterministic enforcement)\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "Run a scoped-control edit. Expect `$ARGUMENTS` to begin with a role name followed by the request.\n\n"
        "```bash\n"
        "scoped-control edit $ARGUMENTS --path .\n"
        "```\n\n"
        "If the edit is blocked, show the `Blocked:` reasons verbatim. Do not retry with a different role.\n"
    ),
    "sc-surfaces.md": (
        "---\n"
        "description: List the scoped-control indexed surfaces for this repo\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "```bash\n"
        "scoped-control surface list --path .\n"
        "```\n"
    ),
}


def install_claude_code(repo_path: Path, *, force: bool = False) -> tuple[str, ...]:
    """Write scoped-control slash commands to `.claude/commands/`."""

    commands_dir = repo_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for filename, body in COMMANDS.items():
        target = commands_dir / filename
        if target.exists() and not force:
            continue
        target.write_text(body, encoding="utf-8")
        written.append(str(target.relative_to(repo_path)))
    return tuple(written)
