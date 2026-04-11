from __future__ import annotations

from pathlib import Path

from scoped_control.cli import main


def test_cli_init_bootstraps_repo(tmp_path, capsys):
    exit_code = main(["init", "--path", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Initialized scoped-control" in captured.out
    assert (tmp_path / ".scoped-control" / "config.yaml").exists()
    assert (tmp_path / ".scoped-control" / "index.json").exists()


def test_cli_check_reports_success(tmp_path, capsys):
    main(["init", "--path", str(tmp_path)])
    capsys.readouterr()

    exit_code = main(["check", "--path", str(tmp_path / "nested")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK:" in captured.out


def test_cli_without_args_prints_guidance(capsys):
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage: scoped-control" in captured.out
    assert "scoped-control setup" in captured.out
