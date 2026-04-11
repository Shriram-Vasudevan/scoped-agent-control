from __future__ import annotations

import json

import pytest

from scoped_control.config.loader import bootstrap_repo, check_repo, load_config
from scoped_control.errors import ConfigValidationError, RepoNotInitializedError


def test_bootstrap_repo_creates_config_and_index(tmp_path):
    paths = bootstrap_repo(tmp_path)

    assert paths.config_path.exists()
    assert paths.index_path.exists()

    index_payload = json.loads(paths.index_path.read_text(encoding="utf-8"))
    assert index_payload["surfaces"] == []
    assert index_payload["warnings"] == []


def test_load_config_returns_typed_model(tmp_path):
    bootstrap_repo(tmp_path)

    paths, config = load_config(tmp_path)

    assert paths.root == tmp_path.resolve()
    assert config.version == 1
    assert config.roles[0].name == "maintainer"
    assert config.roles[0].query_paths == ("**/*",)


def test_load_config_requires_initialized_repo(tmp_path):
    with pytest.raises(RepoNotInitializedError):
        load_config(tmp_path)


def test_invalid_config_returns_actionable_error(tmp_path):
    paths = bootstrap_repo(tmp_path)
    paths.config_path.write_text("roles: nope\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(tmp_path)

    assert "roles must be a list" in str(excinfo.value)


def test_check_repo_reports_failure_for_missing_config(tmp_path):
    report = check_repo(tmp_path)

    assert report.ok is False
    assert "Run `scoped-control init`" in report.errors[0]
