# scoped-agent-control

scoped-agent-control is a framework for enforcing role-based, scoped AI interactions with a codebase.

It allows teams to define exactly who can read or modify which parts of a repository and under what constraints. Simple inline annotations and a repo-level config enable AI agents (e.g. Claude Code, Codex, etc.) to operate within approved, role-specific boundaries.

In practice, this enables non-technical users (e.g. PMs, GTM, etc.) to safely make targeted changes without risking unintended or disallowed side effects across the system.

The default entrypoint is the interactive Textual app. Run `scoped-control` to open the TUI, then use `/setup` to bootstrap a repo and slash commands for the rest.

## Install

Requirements:

- Python 3.12+
- `uv`

Install the repo dependencies:

```bash
uv sync --dev
```

Install the CLI locally so you can run `scoped-control` directly:

```bash
uv tool install -e .
```

If you do not want a tool install, this also works:

```bash
pip install -e .
```

## Quick Start

### 1. Open the TUI

```bash
scoped-control
```

If the repo is not initialized, the setup screen opens automatically inside the app. You can also reopen it any time with `/setup` or by pressing `s`.

### 2. Run the guided setup inside the TUI

```bash
/setup
```

This is the main onboarding flow. It walks you through:

- the role name
- what that role should generally be allowed to do
- whether to auto-insert annotations
- whether to install the GitHub workflow
- whether to enable Slack notifications

What `setup` does in one pass:

- creates `.scoped-control/config.yaml`
- creates `.scoped-control/index.json`
- creates or updates the role you define
- scans the repository
- infers read and edit scope from your plain-English role intent
- auto-inserts annotations across the matched parts of the project
- rebuilds the surface index
- optionally installs GitHub and Slack wiring

### 3. Use the non-interactive CLI setup only if you want automation without the TUI

```bash
scoped-control setup \
  --path . \
  --role recruiter \
  --description "Recruiting copy editor" \
  --intent "Recruiter can update careers copy, role descriptions, and related hiring docs, but should not modify core product code." \
  --install-github \
  --install-slack
```

By default, `setup` uses a planner to infer scope from `--intent`. On machines with Codex or Claude Code installed, it will use a real planner automatically. You can also pin the planner explicitly:

```bash
scoped-control setup --path . --role recruiter --intent "..." --planner-executor codex
```

If you still want to override the scope manually, `--query-path` and `--edit-path` remain available.

### 4. Inspect what was indexed

```bash
/surface list
/surface show careers.openings
```

### 5. Run a scoped query

```bash
/query recruiter Explain the careers page copy --executor codex
```

What this does:

- resolves only the surfaces the role is allowed to read
- ranks likely matches deterministically
- builds a constrained brief
- sends only that approved context to the selected executor

### 6. Run a scoped edit

```bash
/edit recruiter Update the job intro copy --executor codex
```

What this does:

- resolves only the surfaces the role is allowed to edit
- runs the edit in a temporary workspace
- enforces file scope, surface spans, diff limits, dependencies, and validators
- writes changes back only if every check passes

### 7. Re-annotate after changing role paths

```bash
/annotate --role recruiter
```

If you omit `--query-glob` and `--edit-glob`, `annotate` derives them from the role’s configured `query_paths` and `edit_paths`.

### 8. Remove scoped-control artifacts in one shot

```bash
/cleanup --dry-run
/cleanup --force
```

`cleanup` removes the repo artifacts that scoped-control created:

- auto-generated top-of-file annotations
- `.scoped-control/config.yaml` and `.scoped-control/index.json` by deleting `.scoped-control/`
- the installed GitHub workflow file

Use `--dry-run` to preview the cleanup and `--force` to apply it.

## Command Guide

- `scoped-control setup --path .`
  Guided bootstrap. This should be the first command you run in a new repo.
- `scoped-control setup --path . --role <role> --intent "<plain-English capability description>"`
  Non-interactive project-wide setup from general role intent.
- `scoped-control annotate --role <role> --path .`
  Auto-inserts file-level annotations and rebuilds the index.
- `scoped-control cleanup --path . --dry-run`
  Previews removal of generated annotations, `.scoped-control/`, and the installed workflow.
- `scoped-control cleanup --path . --force`
  Applies the destructive cleanup.
- `scoped-control scan --path .`
  Rebuilds the index from the current annotations on disk.
- `scoped-control role list --path .`
  Shows the configured roles.
- `scoped-control role add <role> --query-path "<glob>" --edit-path "<glob>" --path .`
  Adds a role manually.
- `scoped-control role edit <role> --query-path "<glob>" --edit-path "<glob>" --path .`
  Updates a role manually.
- `scoped-control surface list --path .`
  Lists indexed surfaces.
- `scoped-control surface show <surface-id> --path .`
  Shows one indexed surface in detail.
- `scoped-control query <role> <request> --executor codex --path .`
  Runs a scoped read-only request.
- `scoped-control edit <role> <request> --executor codex --path .`
  Runs a scoped edit with deterministic enforcement.
- `scoped-control install github --path .`
  Writes the GitHub Actions remote-edit workflow.
- `scoped-control install slack --path . --webhook-env TEAM_SLACK_WEBHOOK`
  Enables Slack notifications and refreshes the GitHub workflow env wiring.
- `scoped-control remote-edit --path . --event-file event.json`
  Executes the GitHub workflow payload locally.
- `scoped-control tui --path .`
  Opens the optional Textual console.

## GitHub And Slack

Install GitHub remote-edit support:

```bash
scoped-control install github --path .
```

Install Slack notifications:

```bash
scoped-control install slack --path . --webhook-env TEAM_SLACK_WEBHOOK
```

After that:

- set the same webhook env var locally if you want local `edit` notifications
- add the same secret in GitHub Actions if you want `remote-edit` notifications there
- Slack notifications fire for `edit` and `remote-edit` success and blocked outcomes

## Annotation Format

`setup` and `annotate` insert annotations for you. A generated file-scope annotation looks like this:

```python
# surface: careers.openings
# roles: recruiter
# modes: query, edit
# invariants: file_scope
```

Generated annotations are file-scoped by default: one indexed surface per matched file.

Both `#` and `//` comment styles are supported, depending on the file type.

## Supported Fields

- `surface`: unique surface id stored in the index
- `roles`: which roles can access the surface
- `modes`: allowed operations, currently `query` and `edit`
- `invariants`: extra constraints or tags; `file_scope` makes the surface span the whole file
- `depends_on`: readable dependency surfaces that should be included as supporting context
