# scoped-agent-control

scoped-agent-control is a framework for enforcing role-based, scoped AI interactions with a codebase.

It allows teams to define exactly who can read or modify which parts of a repository and under what constraints. Simple inline annotations and a repo-level config enable AI agents (e.g. Claude Code, Codex, etc.) to operate within approved, role-specific boundaries.

In practice, this enables non-technical users (e.g. PMs, GTM, etc.) to safely make targeted changes without risking unintended or disallowed side effects across the system.

## How it works, end to end

```
  ┌───────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
  │  /setup       │ →  │  annotate    │ →  │  index.json  │ →  │  enforce     │
  │  (read+write  │    │  (file-scope │    │  (surfaces   │    │  (deterministic
  │   intents)    │    │   or         │    │   per role)  │    │   checks)    │
  └───────────────┘    │   semantic)  │    └──────┬───────┘    └──────────────┘
                       └──────────────┘           │
                                                  ▼
          ┌───────────────────────────────────────────────────────────────┐
          │        triage  (classifies request → read vs edit             │
          │                 picks narrowest covering role                 │
          │                 blocks when no role qualifies)                │
          └───────────────┬───────────────┬───────────────┬───────────────┘
                          ▼               ▼               ▼
                       TUI /           Slack slash    GitHub
                       Claude Code     command        Actions
                       slash command   (/scoped ...)  workflow_dispatch
```

Every surface in the index is stamped with `roles` and `modes`. Every request goes through `triage` before anything runs: triage decides query vs edit, picks the narrowest role whose scope covers the target files, and blocks the request with a reason if no role qualifies. All four entrypoints — TUI, Claude Code slash commands, Slack, and GitHub — share the same triage + enforcement pipeline, so the same rules apply no matter where the request comes from.

## Install

Requirements: Python 3.12+ and `uv`.

```bash
uv sync --dev
uv tool install -e .        # or: pip install -e .
```

## Quick start — the full coherent flow

The whole point of the system is that you run one command, answer a few plain-English prompts, and then your repo is ready for scoped requests from the TUI, Claude Code, Slack, or GitHub. Here is what that looks like end to end.

### 1. Open the TUI

```bash
scoped-control
```

If the repo has not been initialized, the setup screen opens automatically. You can also reopen it at any time with `/setup` or by pressing `s`.

### 2. Run guided setup — one role, two intents

The setup screen (and `scoped-control setup`) now asks for **read intent** and **write intent** separately, so reads and writes never get conflated:

```
Role name:         recruiter
Description:       Recruiting copy editor
Read intent:       Recruiter should be able to read the careers page, role postings,
                   and the public hiring docs.
Write intent:      Only the careers markdown files. Nothing else is editable.
Planner:           auto       (uses Codex or Claude Code if installed, else heuristic)
Auto-annotate:     ✓
Semantic surfaces: ☐ (on = per-function surfaces placed by the LLM; off = one
                     file-scope header per matched file)
```

scoped-control then:

1. writes `.scoped-control/config.yaml` with the role and its inferred `query_paths` / `edit_paths`,
2. inserts annotations into matched files (file-scope by default, or function/class level if you opted into semantic annotations),
3. rebuilds `.scoped-control/index.json`,
4. optionally installs the GitHub workflows and Slack notification wiring.

You can also run setup fully non-interactively:

```bash
scoped-control setup --path . \
  --role recruiter \
  --description "Recruiting copy editor" \
  --read-intent  "Recruiter reads careers copy, role postings, and hiring docs." \
  --write-intent "Only careers/**/*.md is editable." \
  --semantic-annotations \
  --planner-executor auto
```

### 3. Install the entrypoints you care about

```bash
scoped-control install claude-code --path .   # /.claude/commands/sc-*.md
scoped-control install github       --path .  # remote-edit + remote-triage workflows
scoped-control install slack        --path . --webhook-env SLACK_WEBHOOK_URL
```

After `install claude-code`, a Claude Code session in this repo can run:

- `/sc-setup` — same guided setup, driven by Claude Code
- `/sc-triage <request>` — classify read vs edit, pick a role, show the decision
- `/sc-query <role> <request>` — scoped read
- `/sc-edit <role> <request>` — scoped edit with deterministic enforcement
- `/sc-surfaces` — list indexed surfaces

### 4. Triage any natural-language request

```bash
scoped-control triage "update the careers intro copy" --path .
```

Output:

```
Triage decision: mode=edit role=recruiter triager=auto
Reason: Matched role `recruiter` for edit of 1 target(s).
Targets: careers/openings.md
```

If the same request named a file the role cannot write, triage blocks it up front:

```
Triage decision: mode=blocked role=None triager=heuristic
Reason: No configured role has edit access to the requested target(s).
```

Add `--execute` to actually run the classified action:

```bash
scoped-control triage "explain the careers intro" --execute --executor fake --path .
```

### 5. Slack — incoming slash command with real triage

```bash
export SLACK_SIGNING_SECRET=...            # from your Slack app config
scoped-control serve-slack --path . --port 8787 --executor fake
```

Then tunnel it (`ngrok http 8787`) and point your Slack slash command at `<public>/`. The flow for an incoming `/scoped update the careers intro copy` is:

1. Slack POSTs the form to the server.
2. The server verifies the Slack signing signature (rejects anything older than 5 minutes or with a tampered body).
3. It runs `triage_request` — same code path as the CLI.
4. If triage blocks, Slack gets an ephemeral `:no_entry: blocked: <reason>` reply.
5. If triage allows, it dispatches to `query` or `edit` with the selected role and replies in-channel with the scoped result and the enforcement summary.

### 6. GitHub — two dispatch workflows

`install github` writes two workflows:

- `scoped-control.yml` — explicit remote-edit. Caller picks the role and mode.
- `scoped-control-triage.yml` — remote-triage. Caller provides only the request; triage picks the role and the mode.

On Actions, a remote-triage run looks like:

```
> scoped-control remote-triage --path . --event-file $GITHUB_EVENT_PATH
Triage decision: mode=edit role=recruiter triager=claude_code
Targets: careers/openings.md
... (edit runs, deterministic enforcement, optional Slack notification)
```

## A coherent end-to-end example

This is the flow you described, verified step by step on a fresh repo:

```bash
# 0. Starting point: plain repo with careers/ and src/ folders
$ tree -L 2
.
├── careers
│   ├── intro.md
│   └── openings.md
└── src
    └── core.py

# 1. One command: guided setup with separate read/write intents
$ scoped-control setup --path . \
    --role recruiter \
    --description "Recruiting copy editor" \
    --read-intent  "Recruiter reads careers markdown and hiring docs." \
    --write-intent "Only careers/**/*.md is editable." \
    --planner-executor heuristic

Setup complete.
Step 1: initialized .scoped-control/
Step 2: configured role `recruiter`
Step 3: planned role scope via `heuristic`
Query paths: careers/**
Edit paths: careers/**
Planner reasoning:
- Heuristic matched repo paths: careers/intro.md, careers/openings.md
Step 4: auto-annotated 2 file(s)
Step 5: indexed 2 surface(s)

# 2. Install all three entrypoints
$ scoped-control install claude-code --path .
Command: .claude/commands/sc-setup.md
Command: .claude/commands/sc-triage.md
Command: .claude/commands/sc-query.md
Command: .claude/commands/sc-edit.md
Command: .claude/commands/sc-surfaces.md

$ scoped-control install github --path .
Installed GitHub remote-edit and remote-triage scaffolding.
Edit workflow:   .github/workflows/scoped-control.yml
Triage workflow: .github/workflows/scoped-control-triage.yml

$ scoped-control install slack --path . --webhook-env SLACK_WEBHOOK_URL

# 3. Triage the kind of request a non-technical user would send
$ scoped-control triage "update the careers intro copy" --path .
Triage decision: mode=edit role=recruiter triager=heuristic
Reason: Matched role `recruiter` for edit of 1 target(s).
Targets: careers/intro.md

# 4. The same request sent to src/core.py is blocked BEFORE any executor runs
$ scoped-control triage "refactor src/core.py to use a class" --path .
Triage decision: mode=blocked role=None triager=heuristic
Reason: No configured role has edit access to the requested target(s).
Targets: src/core.py

# 5. An incoming Slack message hits the same triage pipeline
#    POST from Slack  →  signature verified  →  triage  →  query/edit
#    If blocked: ephemeral reply.  If allowed: in-channel reply with results.

# 6. A GitHub workflow_dispatch of scoped-control-triage.yml with input
#    { "request": "update the careers intro copy" }  runs the same pipeline
#    inside CI and opens a diff only when triage + enforcement both approve.
```

Every step — CLI, TUI, Claude Code slash command, Slack message, GitHub workflow — funnels through `triage_request` + the deterministic `enforce_*` passes. No entrypoint can widen scope; every edit is sandboxed, diff-checked, span-checked, and validator-checked before it is applied.

## Command reference

Setup & config

- `scoped-control setup --path . [--role ... --read-intent ... --write-intent ... --semantic-annotations]` — guided bootstrap.
- `scoped-control check --path .` — validate config and index presence.
- `scoped-control scan --path .` — rebuild index from annotations.
- `scoped-control annotate --role <role> [--query-glob ... --edit-glob ...]` — auto-insert annotations.
- `scoped-control cleanup --path . --dry-run | --force` — remove all scoped-control artifacts.

Role and surface inspection

- `scoped-control role list | add | edit | remove`
- `scoped-control surface list | show <id>`
- `scoped-control validator list`

Scoped execution

- `scoped-control triage <request> [--role <pref>] [--execute] [--executor fake|codex|claude_code]` — classify and optionally run.
- `scoped-control query <role> <request>` — scoped read.
- `scoped-control edit <role> <request>` — scoped edit with enforcement.

Entrypoint integrations

- `scoped-control install claude-code [--force]` — write `.claude/commands/sc-*.md`.
- `scoped-control install github [--force]` — write both remote-edit and remote-triage workflows.
- `scoped-control install slack --webhook-env ENV_VAR` — enable outbound notifications and refresh the workflows.
- `scoped-control serve-slack --host 127.0.0.1 --port 8787 [--signing-secret ...]` — run the incoming slash-command server.
- `scoped-control remote-edit   --event-file <path>` — process a remote-edit dispatch payload.
- `scoped-control remote-triage --event-file <path>` — triage and run a remote dispatch payload.

TUI

- `scoped-control tui --path .` — open the Textual console. Press `s` or run `/setup`. Same slash commands work here: `/triage`, `/query`, `/edit`, `/surface list`, `/install claude-code`, …

## Annotation format

File-scope (default, placed by `auto_annotate_repo`):

```python
# surface: careers.openings
# roles: recruiter
# modes: query, edit
# invariants: file_scope
```

Semantic / per-declaration (placed by `semantic_annotate_repo` when you pass `--semantic-annotations`; the LLM picks function and class boundaries and emits one annotation block per surface):

```python
# surface: core.compute_total
# roles: maintainer
# modes: query, edit
# invariants: span_scope
def compute_total(items):
    ...
```

Both `#` and `//` comment styles are supported. Supported fields:

- `surface` — unique id stored in the index.
- `roles` — comma-separated role names that may access this surface (empty = all roles).
- `modes` — `query` and/or `edit`.
- `invariants` — `file_scope` or `span_scope` (others are treated as tags).
- `depends_on` — comma-separated surface ids that should be included as read-only context.

## Deterministic enforcement

Every edit, regardless of entrypoint, is run in a sandbox workspace and then checked against:

- **Span checks** — modifications must stay within the annotated surface's line range.
- **Diff checks** — enforces `limits.max_changed_files` and `limits.max_diff_lines`.
- **Dependency invariants** — `depends_on` surfaces are read-only during edits.
- **Validators** — any `validators:` entry for mode `edit` runs post-change; a non-zero exit blocks the edit.

If any check fails, the edit is rolled back and the entrypoint (TUI line, Slack reply, GitHub log, Claude Code response) shows the blocked reasons verbatim.

## Testing

```bash
uv run pytest
```

The suite covers: annotation parsing and scanning, index store, role CRUD, query and edit resolution, deterministic enforcement (span, diff, validators), GitHub remote-edit and remote-triage, Slack signature verification and dispatch, Claude Code installer, triage classification, and the full guided-setup CLI path.
