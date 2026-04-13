from __future__ import annotations

from scoped_control.config.schema import build_default_config
from scoped_control.setup_planner import collect_repo_inventory, plan_role_scope


def test_plan_role_scope_heuristic_collapses_matched_files_to_directory_glob(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    prompts_dir = repo_root / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "copy.md").write_text("copy\n", encoding="utf-8")
    (prompts_dir / "faq.md").write_text("faq\n", encoding="utf-8")
    (repo_root / "src.py").write_text("print('x')\n", encoding="utf-8")

    plan = plan_role_scope(
        repo_root,
        config=build_default_config(),
        role_name="recruiter",
        description="Recruiting role",
        intent="Recruiter can update prompt copy and markdown in the prompts folder.",
        planner_executor="heuristic",
    )

    assert plan.query_paths == ("prompts/**",)
    assert plan.edit_paths == ("prompts/**",)
    assert plan.annotate_query_globs == ("prompts/**",)
    assert plan.annotate_edit_globs == ("prompts/**",)
    assert plan.planner == "heuristic"


def test_plan_role_scope_heuristic_detects_broad_maintainer_scope(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("readme\n", encoding="utf-8")
    (repo_root / "app.py").write_text("print('x')\n", encoding="utf-8")

    plan = plan_role_scope(
        repo_root,
        config=build_default_config(),
        role_name="maintainer",
        description="Maintainer role",
        intent="Maintainer can edit the entire project.",
        planner_executor="heuristic",
    )

    assert plan.query_paths == ("**/*",)
    assert plan.edit_paths == ("**/*",)
    assert plan.annotate_query_globs == ("**/*",)
    assert plan.annotate_edit_globs == ("**/*",)


def test_collect_repo_inventory_skips_control_and_virtualenv_directories(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
    control_dir = repo_root / ".scoped-control"
    control_dir.mkdir()
    (control_dir / "config.yaml").write_text("version: 1\n", encoding="utf-8")
    venv_dir = repo_root / ".venv"
    venv_dir.mkdir()
    (venv_dir / "ignored.py").write_text("ignored\n", encoding="utf-8")

    inventory = collect_repo_inventory(repo_root)

    assert inventory == ("README.md",)
