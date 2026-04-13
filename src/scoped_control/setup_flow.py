"""Guided setup flow for CLI bootstrap."""

from __future__ import annotations

from pathlib import Path

from scoped_control.annotations.inserter import auto_annotate_repo
from scoped_control.annotations.semantic_inserter import semantic_annotate_repo
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.config.mutator import add_role, update_role, write_config
from scoped_control.index.builder import rebuild_index
from scoped_control.integrations.installer import install_github, install_slack
from scoped_control.models import RoleConfig
from scoped_control.setup_planner import PlannedRoleScope, plan_role_scope


def run_setup(
    repo_path: Path,
    *,
    role_name: str,
    description: str,
    intent: str | None,
    query_paths: tuple[str, ...],
    edit_paths: tuple[str, ...],
    annotate_query_globs: tuple[str, ...],
    annotate_edit_globs: tuple[str, ...],
    planner_executor: str,
    auto_annotate_enabled: bool,
    install_github_enabled: bool,
    install_slack_enabled: bool,
    slack_webhook_env: str,
    force_annotations: bool,
    read_intent: str | None = None,
    write_intent: str | None = None,
    semantic_annotations: bool = False,
) -> tuple[str, ...]:
    """Bootstrap and configure a repo in one guided pass."""

    paths = bootstrap_repo(repo_path, overwrite=False)
    _, config = load_config(paths.root)
    planning_result: PlannedRoleScope | None = None

    if not query_paths and not edit_paths:
        if (not intent or not intent.strip()) and not read_intent and not write_intent:
            raise ValueError(
                "Setup needs either explicit --query-path/--edit-path values, a plain-English --intent, "
                "or separate --read-intent/--write-intent values."
            )
        planning_result = plan_role_scope(
            paths.root,
            config=config,
            role_name=role_name,
            description=description,
            intent=intent or "",
            read_intent=read_intent,
            write_intent=write_intent,
            planner_executor=planner_executor,
        )
        query_paths = planning_result.query_paths
        edit_paths = planning_result.edit_paths
        if not annotate_query_globs:
            annotate_query_globs = planning_result.annotate_query_globs
        if not annotate_edit_globs:
            annotate_edit_globs = planning_result.annotate_edit_globs

    if auto_annotate_enabled and not annotate_query_globs and not annotate_edit_globs:
        annotate_query_globs = query_paths
        annotate_edit_globs = edit_paths

    role = RoleConfig(
        name=role_name,
        description=description,
        query_paths=query_paths,
        edit_paths=edit_paths,
    )
    if any(existing.name == role.name for existing in config.roles):
        config = update_role(config, role)
    else:
        config = add_role(config, role)
    write_config(config, paths.config_path)

    annotation_result = None
    if auto_annotate_enabled:
        if semantic_annotations:
            annotation_result = semantic_annotate_repo(
                paths.root,
                config=config,
                roles=(role.name,),
                query_globs=annotate_query_globs,
                edit_globs=annotate_edit_globs,
                executor=planner_executor,
                force=force_annotations,
                dry_run=False,
            )
        else:
            annotation_result = auto_annotate_repo(
                paths.root,
                roles=(role.name,),
                query_globs=annotate_query_globs,
                edit_globs=annotate_edit_globs,
                force=force_annotations,
                dry_run=False,
            )
    index_result, _ = rebuild_index(paths.root)

    lines: list[str] = []
    step_number = 1

    lines.append(f"Step {step_number}: initialized .scoped-control/")
    step_number += 1
    lines.append(f"Step {step_number}: configured role `{role.name}`")
    step_number += 1
    if planning_result is not None:
        lines.append(f"Step {step_number}: planned role scope via `{planning_result.planner}`")
        lines.append(f"Query paths: {', '.join(planning_result.query_paths) or '<none>'}")
        lines.append(f"Edit paths: {', '.join(planning_result.edit_paths) or '<none>'}")
        if planning_result.reasoning:
            lines.append("Planner reasoning:")
            lines.extend(f"- {item}" for item in planning_result.reasoning)
        step_number += 1
    if annotation_result is None:
        lines.append(
            f"Step {step_number}: config-only mode (no files modified); "
            "role globs alone gate access. Run `scoped-control annotate --role "
            f"{role.name}` later to add per-file overrides or span rules."
        )
    else:
        lines.append(f"Step {step_number}: auto-annotated {len(annotation_result.annotated_files)} file(s)")
    step_number += 1
    lines.append(f"Step {step_number}: indexed {len(index_result.index.surfaces)} explicit surface(s)")
    step_number += 1

    if annotation_result is not None and annotation_result.annotated_files:
        lines.append("Annotated files:")
        lines.extend(f"- {item}" for item in annotation_result.annotated_files)
    if annotation_result is not None and annotation_result.warnings:
        lines.append("Annotation warnings:")
        lines.extend(f"- {item}" for item in annotation_result.warnings)

    if install_github_enabled:
        _, workflow_path, triage_workflow_path = install_github(paths.root, force=True)
        lines.append(f"Step {step_number}: installed GitHub workflows at {workflow_path} and {triage_workflow_path}")
        step_number += 1
    if install_slack_enabled:
        config_path = install_slack(paths.root, webhook_env=slack_webhook_env)
        lines.append(f"Step {step_number}: enabled Slack notifications in {config_path}")

    lines.append("Next commands:")
    lines.append(f"- scoped-control surface list --path {paths.root}")
    lines.append(f"- scoped-control query {role.name} Explain the indexed surfaces --executor codex --path {paths.root}")
    lines.append(f"- scoped-control edit {role.name} Change one approved file --executor codex --path {paths.root}")
    return tuple(lines)
