from __future__ import annotations

from scoped_control.annotations.inserter import remove_auto_annotations


def test_remove_auto_annotations_restores_original_file_content(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = repo_root / "script.py"
    target.write_text(
        "#!/usr/bin/env python3\n"
        "# coding: utf-8\n"
        "# surface: script\n"
        "# roles: writer\n"
        "# modes: query, edit\n"
        "# invariants: file_scope\n"
        "\n"
        "print('hello')\n",
        encoding="utf-8",
    )

    result = remove_auto_annotations(repo_root)

    assert result.cleaned_files == ("script.py",)
    assert result.removed_blocks == 1
    assert target.read_text(encoding="utf-8") == "#!/usr/bin/env python3\n# coding: utf-8\nprint('hello')\n"


def test_remove_auto_annotations_leaves_non_generated_blocks_untouched(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = repo_root / "script.py"
    original = (
        "# surface: custom.surface\n"
        "# roles: writer\n"
        "# modes: query, edit\n"
        "# invariants: file_scope\n"
        "\n"
        "print('hello')\n"
    )
    target.write_text(original, encoding="utf-8")

    result = remove_auto_annotations(repo_root)

    assert result.cleaned_files == ()
    assert result.removed_blocks == 0
    assert target.read_text(encoding="utf-8") == original
