# scoped-control

`scoped-control` is a repo-installed control plane for scoped AI query and edit runs. It is not a model runtime. It resolves scope deterministically from local config plus inline surface annotations, compiles compact execution briefs for an external executor, and enforces policy after the executor returns.

## What v1 ships

- Textual-first console launched by `scoped-control`
- repo-local config in `.scoped-control/config.yaml`
- generated surface index in `.scoped-control/index.json`
- role-aware `/query` and `/edit` routing
- deterministic ranking and brief generation
- local edit sandboxing with post-run diff/span enforcement
- validator gating before approved edits are applied back to the repo
- GitHub workflow scaffolding for remote edit execution

## Install

```bash
uv sync --dev
uv run scoped-control --help
```

The project expects Python 3.12+.

## Quick Start

```bash
scoped-control init
scoped-control scan
scoped-control role list --path .
scoped-control query maintainer "Explain the system prompt" --executor fake --path .
scoped-control edit maintainer "Change return 1 to return 10" --executor fake --path .
scoped-control install github --path .
```

Running `scoped-control` without a subcommand launches the Textual console. The slash-command surface mirrors the main CLI commands:

```text
/scan
/role list
/surface show prompts.system
/query maintainer Explain the assistant prompt --executor fake
/edit maintainer Change return 1 to return 10 --executor fake
/install github
```

## Annotation Format

Only repeated `#` and `//` comment lines are supported in v1. Consecutive annotation lines attach to the next non-empty, non-annotation line.

```text
# surface: prompts.system
# roles: maintainer, reviewer
# modes: query, edit
# invariants: preserve the assistant tone guide
# depends_on: config.behavior
```

Supported fields:

- `surface`
- `roles`
- `modes`
- `invariants`
- `depends_on`

## Local Query Flow

`query` resolves surfaces using:

- role path allowlists from `.scoped-control/config.yaml`
- surface role and mode metadata from the index
- deterministic lexical ranking by surface id, file name, and keyword overlap

The executor receives only the compiled brief plus scoped file excerpts. For local/demo use, `--executor fake` returns a deterministic synthetic answer. Real adapters are wired for:

- `codex exec`
- `claude --print`

If a binary is missing, the command fails with setup guidance instead of widening scope.

## Local Edit Flow

`edit` uses the same resolver, then runs the executor inside a temporary sandbox:

- clean git repos use a temporary git worktree
- dirty or non-git repos fall back to a temporary repo copy

After the executor returns, `scoped-control` deterministically checks:

- changed-file count
- diff-size limits
- out-of-scope file edits
- edits outside indexed surface spans
- dependency-surface changes
- configured validators

Only if every gate passes are the approved file changes copied back into the repo.

## GitHub Remote Mode

Install the workflow scaffold:

```bash
scoped-control install github --path .
```

That writes `.github/workflows/scoped-control.yml` and enables the GitHub integration block in `.scoped-control/config.yaml`.

The generated workflow uses `workflow_dispatch` inputs:

- `role`
- `request`
- `executor`
- `top_k`

It calls:

```bash
scoped-control remote-edit --path . --event-file "$GITHUB_EVENT_PATH"
```

Secrets to provide on GitHub:

- `OPENAI_API_KEY` for Codex-backed runs
- `ANTHROPIC_API_KEY` for Claude Code-backed runs

Slack and email installers are intentionally placeholders in v1 and point back to the GitHub workflow path.

## Demo Repo

See [examples/demo_repo](examples/demo_repo) for a tiny annotated prompt/config repo with a prebuilt `.scoped-control` directory.

## Test Surface

The suite covers:

- config/bootstrap validation
- annotation parsing and index generation
- CLI and TUI command routing
- fake-executor query flow
- sandboxed edit success and deterministic blocking paths
- GitHub installer and remote-edit scaffolding

Run everything with:

```bash
uv run pytest -q
```
