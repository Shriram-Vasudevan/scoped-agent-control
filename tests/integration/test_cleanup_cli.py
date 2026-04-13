from __future__ import annotations

from scoped_control.cli import main


def test_cleanup_cli_dry_run_preserves_repo_state(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "app.py").write_text("print('hello')\n", encoding="utf-8")

    assert main(
        [
            "setup",
            "--path",
            str(repo_root),
            "--role",
            "writer",
            "--description",
            "Writer role",
            "--query-path",
            "app.py",
            "--edit-path",
            "app.py",
            "--install-github",
            "--annotate-files",
        ]
    ) == 0
    capsys.readouterr()

    original = (repo_root / "app.py").read_text(encoding="utf-8")

    exit_code = main(["cleanup", "--path", str(repo_root), "--dry-run"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Cleanup preview complete." in output
    assert "Cleaned annotation: app.py" in output
    assert "Removed directory: .scoped-control/" in output
    assert "Removed file: .github/workflows/scoped-control.yml" in output
    assert (repo_root / ".scoped-control").exists()
    assert (repo_root / ".github" / "workflows" / "scoped-control.yml").exists()
    assert (repo_root / "app.py").read_text(encoding="utf-8") == original


def test_cleanup_cli_force_removes_repo_artifacts(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    original = "print('hello')\n"
    (repo_root / "app.py").write_text(original, encoding="utf-8")

    assert main(
        [
            "setup",
            "--path",
            str(repo_root),
            "--role",
            "writer",
            "--description",
            "Writer role",
            "--query-path",
            "app.py",
            "--edit-path",
            "app.py",
            "--install-github",
            "--annotate-files",
        ]
    ) == 0
    capsys.readouterr()

    exit_code = main(["cleanup", "--path", str(repo_root), "--force"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Removed scoped-control artifacts." in output
    assert not (repo_root / ".scoped-control").exists()
    assert not (repo_root / ".github" / "workflows" / "scoped-control.yml").exists()
    assert (repo_root / "app.py").read_text(encoding="utf-8") == original


def test_cleanup_cli_requires_force_without_dry_run(tmp_path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    exit_code = main(["cleanup", "--path", str(repo_root)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Cleanup is destructive." in captured.err
