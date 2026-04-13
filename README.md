# scoped-agent-control

scoped-agent-control is a framework for enforcing role-based, scoped AI interactions with a codebase.

It allows teams to define exactly who can read or modify which parts of a repository and under what constraints. Simple inline annotations and a repo-level config enable AI agents (e.g. Claude Code, Codex, etc.) to operate within approved, role-specific boundaries.

In practice, this enables non-technical users (e.g. PMs, GTM, etc.) to safely make targeted changes without risking unintended or disallowed side effects across the system.

## Install

```bash
pipx install git+https://github.com/Shriram-Vasudevan/scoped-agent-control
# or
uv tool install git+https://github.com/Shriram-Vasudevan/scoped-agent-control
```

Both put `scoped-control` on PATH globally. Requires Python 3.12+.

For local development:

```bash
git clone https://github.com/Shriram-Vasudevan/scoped-agent-control
cd scoped-agent-control
uv sync --dev
uv run scoped-control
```

## Quick start

```bash
cd path/to/any/repo
scoped-control
```

The TUI opens. On first run, a wizard asks four questions — role name, description, what to read, what to edit. Press Enter to accept defaults. Setup writes `.scoped-control/config.yaml` and drops into the main console.

## Commands

Type slash commands at the TUI prompt:

| Command | Purpose |
|---|---|
| `/setup` (or `/init`) | Guided role wizard |
| `/role list \| add \| edit \| remove` | Manage roles |
| `/surface list \| show <id>` | Inspect indexed surfaces |
| `/scan` | Rebuild the index |
| `/query <role> <request>` | Scoped read |
| `/edit <role> <request>` | Scoped edit with enforcement |
| `/annotate --role <name>` | Add file-scope annotations |
| `/cleanup --dry-run \| --force` | Remove all artifacts |
| `/install claude-code \| github \| slack` | Install integrations |
| `/help`, `/clear`, `/quit` | TUI controls |

The same commands work as CLI subcommands without the slash:

```bash
scoped-control role list
scoped-control query maintainer "explain the auth flow"
scoped-control edit recruiter "update the careers intro" --executor codex
```

CLI-only commands (long-running or guided):

| Command | Purpose |
|---|---|
| `triage <request>` | Classify a request without running it |
| `install slack-bot` | Guided Slack bot setup with auto-tunneling |
| `serve-slack` | Run the Slack bot server |
| `remote-edit --event-file <path>` | Process a GitHub remote-edit payload |
| `remote-triage --event-file <path>` | Process a GitHub remote-triage payload |

## End-to-end example

```bash
$ cd ~/my-repo
$ scoped-control
# Wizard:
#   Role name → recruiter
#   Description → Recruiting copy editor
#   Read → careers folder and hiring docs
#   Write → only careers/**/*.md
# Output: Role `recruiter` created.

# In the TUI prompt:
> /query recruiter what does the careers intro say
> /edit recruiter update the careers intro to mention remote work

# Or from a shell:
$ scoped-control triage "refactor src/auth.py"
Triage decision: mode=blocked role=None
Reason: No configured role has edit access to the requested target(s).
```

## Slack bot

```bash
scoped-control install slack-bot
```

A guided five-step flow:

1. Starts a public tunnel (`cloudflared` preferred, `ngrok` fallback).
2. Prints a Slack app manifest with the URL pre-filled.
3. Prompts for the Signing Secret.
4. Waits for "Install to Workspace" in the Slack admin UI.
5. Smoke-tests the round trip and prints a team announcement template.

Total time: ~3 minutes. Requires `cloudflared` or `ngrok` on PATH. The tunnel URL is valid only while the process runs; production deployments need a stable domain.

## GitHub workflows

```bash
scoped-control install github
```

Writes two `workflow_dispatch` workflows:

- `scoped-control.yml` — explicit role + request.
- `scoped-control-triage.yml` — triage picks the role and mode from a request alone.

Add `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` as Actions secrets before running.

## Claude Code slash commands

```bash
scoped-control install claude-code
```

Writes `.claude/commands/sc-{setup,triage,query,edit,surfaces}.md`. The slash commands work inside any Claude Code session in the repo.

## Annotations

Setup writes config only; no files are modified. Files matching a role's globs are accessible without per-file annotations — the resolver synthesizes whole-file surfaces on demand.

Annotations are inline overrides for two cases:

- Carve-outs — restrict one file to a narrower role than its directory's role.
- Span rules — `invariants: span_scope` limits edits to a specific function or class.

```python
# surface: core.compute_total
# roles: maintainer
# modes: query, edit
# invariants: span_scope
def compute_total(items):
    ...
```

Fields: `surface`, `roles`, `modes`, `invariants`, `depends_on`. `#` and `//` comment styles supported.

Apply with `/annotate --role <name>` or `scoped-control setup --annotate-files`.

## Enforcement

Edits run in a sandbox workspace and pass through:

- **Scope** — target file matches `edit_paths`.
- **Span** — modifications stay within the target surface's line range.
- **Diff limit** — `limits.max_changed_files`, `limits.max_diff_lines`.
- **Validators** — commands listed under `validators:` with mode `edit`.

Failures roll back the sandbox and surface the reason.

## Configuration

`.scoped-control/config.yaml`:

```yaml
roles:
  - name: recruiter
    description: Recruiting copy editor
    query_paths: ["careers/**"]
    edit_paths: ["careers/**/*.md"]

limits:
  max_changed_files: 5
  max_diff_lines: 400

validators:
  - name: lint
    command: "ruff check"
    modes: [edit]
```

## Testing

```bash
uv run pytest
```
