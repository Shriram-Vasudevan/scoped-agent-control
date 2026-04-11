"""Schema helpers for .scoped-control/config.yaml."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scoped_control.errors import ConfigValidationError
from scoped_control.models import (
    AppConfig,
    EmailIntegrationConfig,
    ExecutorConfig,
    ExecutorsConfig,
    GitHubIntegrationConfig,
    IntegrationsConfig,
    LimitsConfig,
    RoleConfig,
    SlackIntegrationConfig,
    ValidatorConfig,
)

SUPPORTED_MODES = {"query", "edit"}


def build_default_config() -> AppConfig:
    """Return the canonical v1 bootstrap config."""

    return AppConfig(
        version=1,
        default_provider="claude_code",
        roles=(
            RoleConfig(
                name="maintainer",
                description="Default repo operator. Narrow query/edit paths before production use.",
                query_paths=("**/*",),
                edit_paths=(),
            ),
        ),
        validators=(),
        integrations=IntegrationsConfig(
            github=GitHubIntegrationConfig(enabled=False, workflow_path=".github/workflows/scoped-control.yml"),
            slack=SlackIntegrationConfig(
                enabled=False,
                webhook_url_env="SLACK_WEBHOOK_URL",
                notify_on=("edit_success", "edit_blocked", "remote_edit_success", "remote_edit_blocked"),
            ),
            email=EmailIntegrationConfig(enabled=False),
        ),
        limits=LimitsConfig(max_changed_files=5, max_diff_lines=400),
        executors=ExecutorsConfig(
            default="claude_code",
            codex=ExecutorConfig(command=("codex",), query_args=("exec",), edit_args=("exec",)),
            claude_code=ExecutorConfig(command=("claude",)),
        ),
    )


def default_config_dict() -> dict[str, object]:
    """Return a YAML-safe mapping for bootstrap and mutation writes."""

    config = build_default_config()
    return config_to_dict(config)


def load_config_model(raw: Mapping[str, object]) -> AppConfig:
    """Validate and coerce raw YAML into typed config."""

    version = raw.get("version", 1)
    if not isinstance(version, int):
        raise ConfigValidationError("version must be an integer", field="version")
    if version != 1:
        raise ConfigValidationError(f"unsupported config version: {version}", field="version")

    default_provider = raw.get("default_provider", "claude_code")
    if not isinstance(default_provider, str) or not default_provider.strip():
        raise ConfigValidationError("default_provider must be a non-empty string", field="default_provider")

    roles_raw = raw.get("roles", [])
    roles = _parse_roles(roles_raw)

    validators_raw = raw.get("validators", [])
    validators = _parse_validators(validators_raw)

    integrations_raw = raw.get("integrations", {})
    integrations = _parse_integrations(integrations_raw)

    limits_raw = raw.get("limits", {})
    limits = _parse_limits(limits_raw)

    executors_raw = raw.get("executors", {})
    executors = _parse_executors(executors_raw)

    return AppConfig(
        version=version,
        default_provider=default_provider.strip(),
        roles=roles,
        validators=validators,
        integrations=integrations,
        limits=limits,
        executors=executors,
    )


def config_to_dict(config: AppConfig) -> dict[str, object]:
    """Convert typed config back to a canonical YAML-safe mapping."""

    return {
        "version": config.version,
        "default_provider": config.default_provider,
        "roles": [
            {
                "name": role.name,
                "description": role.description,
                "query_paths": list(role.query_paths),
                "edit_paths": list(role.edit_paths),
            }
            for role in config.roles
        ],
        "validators": [
            {
                "name": validator.name,
                "command": validator.command,
                "modes": list(validator.modes),
                "timeout_seconds": validator.timeout_seconds,
            }
            for validator in config.validators
        ],
        "integrations": {
            "github": {
                "enabled": config.integrations.github.enabled,
                "workflow_path": config.integrations.github.workflow_path,
            },
            "slack": {
                "enabled": config.integrations.slack.enabled,
                "webhook_url_env": config.integrations.slack.webhook_url_env,
                "notify_on": list(config.integrations.slack.notify_on),
            },
            "email": {
                "enabled": config.integrations.email.enabled,
            },
        },
        "limits": {
            "max_changed_files": config.limits.max_changed_files,
            "max_diff_lines": config.limits.max_diff_lines,
        },
        "executors": {
            "default": config.executors.default,
            "codex": {
                "command": list(config.executors.codex.command),
                "query_args": list(config.executors.codex.query_args),
                "edit_args": list(config.executors.codex.edit_args),
            },
            "claude_code": {
                "command": list(config.executors.claude_code.command),
                "query_args": list(config.executors.claude_code.query_args),
                "edit_args": list(config.executors.claude_code.edit_args),
            },
        },
    }


def _parse_roles(raw: object) -> tuple[RoleConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ConfigValidationError("roles must be a list", field="roles")

    seen: set[str] = set()
    roles: list[RoleConfig] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ConfigValidationError(f"roles[{index}] must be a mapping", field=f"roles[{index}]")
        name = _as_non_empty_string(item.get("name"), f"roles[{index}].name")
        if name in seen:
            raise ConfigValidationError(f"duplicate role name: {name}", field=f"roles[{index}].name")
        seen.add(name)
        description = _as_string(item.get("description", ""), f"roles[{index}].description")
        query_paths = _as_string_tuple(item.get("query_paths", []), f"roles[{index}].query_paths")
        edit_paths = _as_string_tuple(item.get("edit_paths", []), f"roles[{index}].edit_paths")
        roles.append(RoleConfig(name=name, description=description, query_paths=query_paths, edit_paths=edit_paths))
    return tuple(roles)


def _parse_validators(raw: object) -> tuple[ValidatorConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ConfigValidationError("validators must be a list", field="validators")

    validators: list[ValidatorConfig] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ConfigValidationError(f"validators[{index}] must be a mapping", field=f"validators[{index}]")
        name = _as_non_empty_string(item.get("name"), f"validators[{index}].name")
        command = _as_non_empty_string(item.get("command"), f"validators[{index}].command")
        modes = _as_string_tuple(item.get("modes", ["edit"]), f"validators[{index}].modes")
        invalid_modes = [mode for mode in modes if mode not in SUPPORTED_MODES]
        if invalid_modes:
            raise ConfigValidationError(
                f"validators[{index}].modes contains unsupported values: {', '.join(invalid_modes)}",
                field=f"validators[{index}].modes",
            )
        timeout = item.get("timeout_seconds", 300)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ConfigValidationError(
                "validators timeout_seconds must be a positive integer",
                field=f"validators[{index}].timeout_seconds",
            )
        validators.append(ValidatorConfig(name=name, command=command, modes=modes, timeout_seconds=timeout))
    return tuple(validators)


def _parse_integrations(raw: object) -> IntegrationsConfig:
    data = _as_mapping(raw, "integrations")
    github_data = _as_mapping(data.get("github", {}), "integrations.github")
    slack_data = _as_mapping(data.get("slack", {}), "integrations.slack")
    email_data = _as_mapping(data.get("email", {}), "integrations.email")
    github = GitHubIntegrationConfig(
        enabled=_as_bool(github_data.get("enabled", False), "integrations.github.enabled"),
        workflow_path=_as_string(
            github_data.get("workflow_path", ".github/workflows/scoped-control.yml"),
            "integrations.github.workflow_path",
        ),
    )
    slack = SlackIntegrationConfig(
        enabled=_as_bool(slack_data.get("enabled", False), "integrations.slack.enabled"),
        webhook_url_env=_as_string(
            slack_data.get("webhook_url_env", "SLACK_WEBHOOK_URL"),
            "integrations.slack.webhook_url_env",
        ),
        notify_on=_as_string_tuple(
            slack_data.get("notify_on", ["edit_success", "edit_blocked", "remote_edit_success", "remote_edit_blocked"]),
            "integrations.slack.notify_on",
        ),
    )
    email = EmailIntegrationConfig(enabled=_as_bool(email_data.get("enabled", False), "integrations.email.enabled"))
    return IntegrationsConfig(github=github, slack=slack, email=email)


def _parse_limits(raw: object) -> LimitsConfig:
    data = _as_mapping(raw, "limits")
    max_changed_files = data.get("max_changed_files", 5)
    max_diff_lines = data.get("max_diff_lines", 400)
    if not isinstance(max_changed_files, int) or max_changed_files <= 0:
        raise ConfigValidationError("limits.max_changed_files must be a positive integer", field="limits.max_changed_files")
    if not isinstance(max_diff_lines, int) or max_diff_lines <= 0:
        raise ConfigValidationError("limits.max_diff_lines must be a positive integer", field="limits.max_diff_lines")
    return LimitsConfig(max_changed_files=max_changed_files, max_diff_lines=max_diff_lines)


def _parse_executors(raw: object) -> ExecutorsConfig:
    data = _as_mapping(raw, "executors")
    default = _as_string(data.get("default", "claude_code"), "executors.default")
    codex = _parse_executor_config(data.get("codex", {}), "executors.codex", ("codex",), ("exec",), ("exec",))
    claude_code = _parse_executor_config(data.get("claude_code", {}), "executors.claude_code", ("claude",), (), ())
    return ExecutorsConfig(default=default, codex=codex, claude_code=claude_code)


def _parse_executor_config(
    raw: object,
    field: str,
    default_command: tuple[str, ...],
    default_query_args: tuple[str, ...],
    default_edit_args: tuple[str, ...],
) -> ExecutorConfig:
    data = _as_mapping(raw, field)
    command = _as_string_tuple(data.get("command", list(default_command)), f"{field}.command")
    query_args = _as_string_tuple(data.get("query_args", list(default_query_args)), f"{field}.query_args")
    edit_args = _as_string_tuple(data.get("edit_args", list(default_edit_args)), f"{field}.edit_args")
    return ExecutorConfig(command=command, query_args=query_args, edit_args=edit_args)


def _as_mapping(raw: object, field: str) -> Mapping[str, object]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigValidationError(f"{field} must be a mapping", field=field)
    return raw


def _as_string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise ConfigValidationError(f"{field} must be a string", field=field)
    return raw.strip()


def _as_non_empty_string(raw: object, field: str) -> str:
    value = _as_string(raw, field)
    if not value:
        raise ConfigValidationError(f"{field} may not be empty", field=field)
    return value


def _as_string_tuple(raw: object, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ConfigValidationError(f"{field} must be a list of strings", field=field)
    values: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise ConfigValidationError(f"{field}[{index}] must be a string", field=f"{field}[{index}]")
        stripped = item.strip()
        if not stripped:
            raise ConfigValidationError(f"{field}[{index}] may not be empty", field=f"{field}[{index}]")
        values.append(stripped)
    return tuple(values)


def _as_bool(raw: object, field: str) -> bool:
    if not isinstance(raw, bool):
        raise ConfigValidationError(f"{field} must be a boolean", field=field)
    return raw
