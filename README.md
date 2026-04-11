# scoped-agent-control

scoped-agent-control is a framework for enforcing role-based, scoped AI interactions with a codebase.

It allows teams to define exactly who can read or modify which parts of a repository and under what constraints. Simple inline annotations and a repo-level config enable AI agents (e.g. Claude Code, Codex, etc.) to operate within approved, role-specific boundaries.

In practice, this enables non-technical users (e.g. PMs, GTM, etc.) to safely make targeted changes without risking unintended or disallowed side effects across the system.

The CLI entrypoint is `scoped-control`.

## Install

Requirements:

- Python 3.12+
- `uv`

Install dependencies:

```bash
uv sync --dev
```

Check the CLI:

```bash
uv run scoped-control --help
```

## Quick Start

Initialize the repo:

```bash
scoped-control init --path .
```

What it does:

- creates `.scoped-control/config.yaml`
- creates `.scoped-control/index.json`
- gives you a default `maintainer` role to start from

Add inline annotations to the files you want to expose to AI:

```text
# surface: prompts.system
# roles: maintainer, reviewer
# modes: query, edit
# invariants: preserve the assistant tone guide
# depends_on: config.behavior
```

Build the index from annotations:

```bash
scoped-control scan --path .
```

What it does:

- scans the repo for supported annotation lines
- builds `.scoped-control/index.json`
- records warnings for malformed annotations or duplicate surface ids

Inspect the configured roles:

```bash
scoped-control role list --path .
```

Inspect indexed surfaces:

```bash
scoped-control surface list --path .
scoped-control surface show prompts.system --path .
```

Run a scoped query:

```bash
scoped-control query maintainer Explain the assistant prompt --executor fake --path .
```

What it does:

- resolves surfaces the role is allowed to query
- ranks likely matches deterministically
- compiles a brief with only the approved file excerpts
- sends that scoped brief to the selected executor

Run a scoped edit:

```bash
scoped-control edit maintainer Change return 1 to return 10 --executor fake --path .
```

What it does:

- resolves surfaces the role is allowed to edit
- runs the executor in a temporary sandbox
- blocks edits that exceed file, span, dependency, diff-size, or validator constraints
- only applies changes back to the repo if all checks pass

Install GitHub remote scaffolding:

```bash
scoped-control install github --path .
```

What it does:

- writes `.github/workflows/scoped-control.yml`
- enables the GitHub integration block in `.scoped-control/config.yaml`
- sets the repo up so GitHub Actions can invoke `scoped-control remote-edit`

Launch the Textual console:

```bash
scoped-control
```

The TUI mirrors the CLI with slash commands such as:

```text
/scan
/role list
/surface show prompts.system
/query maintainer Explain the assistant prompt --executor fake
/edit maintainer Change return 1 to return 10 --executor fake
/install github
```

See [examples/demo_repo](examples/demo_repo) for a small working example repo.

## Annotation Format

v1 supports only repeated `#` and `//` comment lines.

Rules:

- consecutive annotation lines attach to the next non-empty, non-annotation line
- the annotated block starts at that next content line
- the block ends at the next annotation run or a simple inferred boundary
- malformed annotations produce warnings instead of crashing the scan

Example:

```text
# surface: prompts.system
# roles: maintainer, reviewer
# modes: query, edit
# invariants: preserve the assistant tone guide
# depends_on: config.behavior
```

## Supported Fields

- `surface`
  Defines the surface id for the annotated block.
- `roles`
  Lists which roles can access the surface.
- `modes`
  Lists whether the surface supports `query`, `edit`, or both.
- `invariants`
  Adds human-readable constraints that are included in execution briefs.
- `depends_on`
  Declares related surfaces that may be included as read-only context.
