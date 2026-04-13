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

If the repo has not been initialized, a conversational setup wizard starts automatically in the same log/input view you're already in. Restart it any time with `/setup` (or `/init`), abort mid-flow with `/cancel`.

### 2. Run guided setup — one role, four questions

The wizard asks four questions, one at a time, in the same input. Defaults show as placeholder text; press Enter to accept any of them:

```
Step 1 of 4  Role name
  Short name. Examples: maintainer, docs-writer, recruiter, test-author.
  Press Enter to use: maintainer

Step 2 of 4  Describe this role in one line
  What does this person or agent actually do?
  Press Enter to use: Scoped operator for <repo-name>

Step 3 of 4  What should this role be allowed to READ?
  Plain English. e.g. 'the careers page and hiring docs'. 'everything' is valid.
  Press Enter to use: everything

Step 4 of 4  What should this role be allowed to WRITE / EDIT?
  Plain English. Say 'none' for read-only, or name the narrowest set of files.
  Press Enter to use: none
```

scoped-control then:

1. writes `.scoped-control/config.yaml` with the role and its inferred `query_paths` / `edit_paths`,
2. **does not touch any files by default** — this is config-only mode; the resolver synthesizes whole-file surfaces on demand for anything the role's globs cover,
3. writes an empty `.scoped-control/index.json` (nothing to index until you opt into explicit annotations).

You can also run setup fully non-interactively:

```bash
scoped-control setup --path . \
  --role recruiter \
  --description "Recruiting copy editor" \
  --read-intent  "Recruiter reads careers copy, role postings, and hiring docs." \
  --write-intent "Only careers/**/*.md is editable." \
  --planner-executor auto
```

Add `--annotate-files` if you want scoped-control to stamp file-scope annotation headers into every matched file at setup time. Skip the flag unless you specifically need per-file overrides or span rules — see [Annotations are opt-in overrides](#annotations-are-opt-in-overrides) below.

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
scoped-control install slack-bot --path .
```

That one command is a ~3-minute guided flow:

1. Starts a public tunnel automatically (`cloudflared` preferred, `ngrok` as fallback; the command tells you how to install either if neither is present).
2. Prints a ready-to-paste Slack app manifest with the public URL already filled in. Paste it into [https://api.slack.com/apps?new_app=1](https://api.slack.com/apps?new_app=1) under "From a manifest".
3. Prompts for the Signing Secret (hidden input).
4. Waits for you to click Install to Workspace in Slack, then press Enter.
5. Starts the local server, sends a signed smoke-test request through the tunnel, and prints a team announcement template you can paste directly into Slack.

After that the server and tunnel stay running in the foreground until Ctrl+C. If the tunnel URL changes (it does when the process restarts), re-run `install slack-bot` — it'll give you the new URL and tell you where to paste it in Slack.

If you already have a signing secret exported and just want the server, the lower-level command still works:

```bash
export SLACK_SIGNING_SECRET=...
scoped-control serve-slack --path . --port 8787 --executor fake
```

The request flow is the same for both: Slack POST → signature verified → `triage_request` (same code path as the CLI) → blocked with an ephemeral reply if the role can't cover it, or dispatched to `query` / `edit` with an in-channel reply showing the scoped result and enforcement summary.

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
Step 4: config-only mode (no files modified); role globs alone gate access.
        Run `scoped-control annotate --role recruiter` later to add per-file
        overrides or span rules.
Step 5: indexed 0 explicit surface(s)

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
- `scoped-control install slack-bot [--port 8787] [--executor ...]` — guided ~3-minute setup of the incoming slash-command bot, including auto-tunneling and a ready-to-paste Slack manifest.
- `scoped-control serve-slack --host 127.0.0.1 --port 8787 [--signing-secret ...]` — run the incoming slash-command server by hand (use `install slack-bot` if you haven't set it up yet).
- `scoped-control remote-edit   --event-file <path>` — process a remote-edit dispatch payload.
- `scoped-control remote-triage --event-file <path>` — triage and run a remote dispatch payload.

TUI

- `scoped-control` (or `scoped-control tui --path .`) — open the conversational Textual console. On an uninitialized repo the setup wizard starts automatically. Slash commands that work inside the TUI: `/setup`, `/init`, `/role list`, `/surface list`, `/scan`, `/query <role> <request>`, `/edit <role> <request>`, `/annotate`, `/cleanup --force`, `/install <target>`, `/help`, `/clear`, `/quit`. (`triage`, `remote-triage`, and `serve-slack` are CLI-only.)

## Annotations are opt-in overrides

**Policy model: config is the floor, annotations tighten further if present.** For most roles, the config alone (role globs in `.scoped-control/config.yaml`) is the whole policy — the resolver synthesizes whole-file surfaces on demand for any file a role's globs cover, so you do not need a per-file header to make a file accessible.

You insert annotations only when you want to *override* the default for a specific file or chunk. Three cases where annotations earn their keep:

1. **Carve-outs.** A broadly-scoped role can read a file, but one specific file should be restricted to a narrower role.
2. **Span rules.** `invariants: span_scope` on a function so edits can't bleed outside it.
3. **Dependency hints.** `depends_on: ...` so queries pull in related context automatically.

Placement options:

- `scoped-control annotate --role <name>` — stamp file-scope headers into matched files (or pass `--query-glob` / `--edit-glob` for narrower targets).
- `scoped-control setup --annotate-files ...` — do both steps in one shot at setup time.
- `scoped-control setup --semantic-annotations ...` — opt into per-function surfaces placed by an LLM (Codex or Claude Code, if installed).

Annotation syntax. File-scope (whole file is one surface):

```python
# surface: careers.openings
# roles: recruiter
# modes: query, edit
# invariants: file_scope
```

Span-scope (a specific function or class is a surface):

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
- `roles` — comma-separated role names that may access this surface (empty = anyone whose role globs cover this file).
- `modes` — `query` and/or `edit`.
- `invariants` — `file_scope` or `span_scope` (others are treated as tags). An additional `implicit` tag appears on synthesized in-memory surfaces; you never write it yourself.
- `depends_on` — comma-separated surface ids that should be included as read-only context.

## Deterministic enforcement

Every edit, regardless of entrypoint, is run in a sandbox workspace and then checked against:

- **Scope** — the edit target surface's file must be covered by the role's `edit_paths`. Files outside that glob are blocked before the edit even runs. This is the first line of defense whether or not the file has an explicit annotation.
- **Span checks** — modifications must stay within the target surface's line range. For explicit `span_scope` surfaces that's the function/class; for explicit file-scope surfaces or for synthesized implicit surfaces that's the whole file.
- **Diff checks** — enforces `limits.max_changed_files` and `limits.max_diff_lines`.
- **Dependency invariants** — `depends_on` surfaces are read-only during edits.
- **Validators** — any `validators:` entry for mode `edit` runs post-change; a non-zero exit blocks the edit.

If any check fails, the edit is rolled back and the entrypoint (TUI log line, Slack reply, GitHub log) shows the blocked reasons verbatim.

## Testing

```bash
uv run pytest
```

The suite covers: annotation parsing and scanning, index store, role CRUD, query and edit resolution, deterministic enforcement (span, diff, validators), GitHub remote-edit and remote-triage, Slack signature verification and dispatch, Claude Code installer, triage classification, and the full guided-setup CLI path.
