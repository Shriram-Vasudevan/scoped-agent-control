"""Canonical YAML writes for config mutation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from scoped_control.config.schema import config_to_dict
from scoped_control.errors import ConfigValidationError
from scoped_control.models import AppConfig, RoleConfig


def write_config(config: AppConfig, path: Path) -> None:
    """Write config in canonical YAML form."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(config_to_dict(config), sort_keys=False, allow_unicode=False)
    path.write_text(rendered, encoding="utf-8")


def add_role(config: AppConfig, role: RoleConfig) -> AppConfig:
    if any(existing.name == role.name for existing in config.roles):
        raise ConfigValidationError(f"role already exists: {role.name}", field="roles")
    return replace(config, roles=(*config.roles, role))


def update_role(config: AppConfig, role: RoleConfig) -> AppConfig:
    found = False
    updated_roles: list[RoleConfig] = []
    for existing in config.roles:
        if existing.name == role.name:
            updated_roles.append(role)
            found = True
        else:
            updated_roles.append(existing)
    if not found:
        raise ConfigValidationError(f"unknown role: {role.name}", field="roles")
    return replace(config, roles=tuple(updated_roles))


def remove_role(config: AppConfig, role_name: str) -> AppConfig:
    updated_roles = tuple(role for role in config.roles if role.name != role_name)
    if len(updated_roles) == len(config.roles):
        raise ConfigValidationError(f"unknown role: {role_name}", field="roles")
    return replace(config, roles=updated_roles)
