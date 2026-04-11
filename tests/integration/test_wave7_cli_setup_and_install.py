from __future__ import annotations

from pathlib import Path

import yaml

from scoped_control.cli import main
from scoped_control.config.loader import bootstrap_repo, load_config
from scoped_control.index.store import load_index


def test_setup_bootstraps_role_config_annotations_and_index(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    (repo_root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_root / "guide.md").write_text("# Guide\n", encoding="utf-8")

    exit_code = main(
        [
            "setup",
            "--path",
            str(repo_root),
            "--role",
            "writer",
            "--description",
            "Writer role",
            "--query-path",
            "guide.md",
            "--edit-path",
            "app.py",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Setup complete." in output
    assert "Step 3: auto-annotated 2 file(s)" in output
    assert "Step 4: indexed 2 surface(s)" in output

    _, config = load_config(repo_root)
    assert config.get_role("writer").description == "Writer role"
    assert config.get_role("writer").query_paths == ("guide.md",)
    assert config.get_role("writer").edit_paths == ("app.py",)

    app_text = (repo_root / "app.py").read_text(encoding="utf-8")
    guide_text = (repo_root / "guide.md").read_text(encoding="utf-8")
    assert app_text.startswith("# surface: app\n")
    assert "# roles: writer" in app_text
    assert "# modes: edit" in app_text
    assert guide_text.startswith("# surface: guide\n")
    assert "# roles: writer" in guide_text
    assert "# modes: query" in guide_text

    index = load_index(repo_root / ".scoped-control" / "index.json")
    assert {surface.id for surface in index.surfaces} == {"app", "guide"}
    assert yaml.safe_load((repo_root / ".scoped-control" / "config.yaml").read_text(encoding="utf-8"))["roles"]


def test_annotate_derives_globs_from_role_paths_when_omitted(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    (repo_root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_root / "guide.md").write_text("# Guide\n", encoding="utf-8")

    main(
        [
            "role",
            "add",
            "writer",
            "--path",
            str(repo_root),
            "--description",
            "Writer role",
            "--query-path",
            "guide.md",
            "--edit-path",
            "app.py",
        ]
    )
    capsys.readouterr()

    exit_code = main(["annotate", "--path", str(repo_root), "--role", "writer"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Query globs: guide.md" in output
    assert "Edit globs: app.py" in output
    assert "Annotated files: 2" in output
    assert "Reindexed surfaces: 2" in output

    app_text = (repo_root / "app.py").read_text(encoding="utf-8")
    guide_text = (repo_root / "guide.md").read_text(encoding="utf-8")
    assert "# surface: app" in app_text
    assert "# modes: edit" in app_text
    assert "# surface: guide" in guide_text
    assert "# modes: query" in guide_text

    index = load_index(repo_root / ".scoped-control" / "index.json")
    assert {surface.id for surface in index.surfaces} == {"app", "guide"}


def test_slack_install_enables_config_and_refreshes_workflow(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bootstrap_repo(repo_root)
    workflow_path = repo_root / ".github" / "workflows" / "scoped-control.yml"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text("name: old workflow\n", encoding="utf-8")

    exit_code = main(
        [
            "install",
            "slack",
            "--path",
            str(repo_root),
            "--webhook-env",
            "TEAM_SLACK_WEBHOOK",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Installed Slack notification wiring." in output

    _, config = load_config(repo_root)
    assert config.integrations.slack.enabled is True
    assert config.integrations.slack.webhook_url_env == "TEAM_SLACK_WEBHOOK"
    assert config.integrations.slack.notify_on == (
        "edit_success",
        "edit_blocked",
        "remote_edit_success",
        "remote_edit_blocked",
    )

    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert "name: scoped-control remote edit" in workflow_text
    assert "TEAM_SLACK_WEBHOOK: ${{ secrets.TEAM_SLACK_WEBHOOK }}" in workflow_text
    assert "name: old workflow" not in workflow_text
