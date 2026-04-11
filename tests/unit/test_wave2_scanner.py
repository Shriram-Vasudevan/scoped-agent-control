from __future__ import annotations

from pathlib import Path

from scoped_control.annotations.scanner import scan_file
from scoped_control.index.builder import build_index


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_scan_file_parses_python_repeated_annotations() -> None:
    surfaces, warnings = scan_file(FIXTURES / "python_repeated_annotations.py", FIXTURES)

    assert warnings == ()
    assert [surface.id for surface in surfaces] == ["python.primary", "python.secondary"]

    primary = surfaces[0]
    secondary = surfaces[1]
    assert primary.file == "python_repeated_annotations.py"
    assert primary.line_start == 7
    assert primary.line_end == 8
    assert primary.roles == ("maintainer", "reviewer")
    assert primary.modes == ("query", "edit")
    assert primary.depends_on == ("shared.helpers",)
    assert primary.hash

    assert secondary.line_start == 17
    assert secondary.line_end == 18
    assert secondary.modes == ("query",)


def test_build_index_warns_and_skips_duplicate_surface_ids() -> None:
    result = build_index(FIXTURES)

    assert result.files_scanned == 5
    assert [surface.id for surface in result.index.surfaces] == [
        "shared.duplicate",
        "plaintext.primary",
        "plaintext.secondary",
        "python.primary",
        "python.secondary",
        "typescript.primary",
        "typescript.secondary",
    ]
    assert any("missing a `surface` field" in warning for warning in result.warnings)
    assert any("duplicate surface id `shared.duplicate`" in warning for warning in result.warnings)
