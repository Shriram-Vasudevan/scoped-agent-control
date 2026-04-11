from __future__ import annotations

import json
from pathlib import Path

from scoped_control.index.store import load_index, write_index


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


def test_expected_index_fixture_loads_without_rescanning(tmp_path) -> None:
    fixture_path = FIXTURES / "index.json"
    loaded = load_index(fixture_path)

    assert loaded.root == "tests/fixtures/wave2"
    assert {surface.id for surface in loaded.surfaces} == {
        "python.primary",
        "python.secondary",
        "typescript.primary",
        "typescript.secondary",
        "plaintext.primary",
        "plaintext.secondary",
    }
    assert all(surface.hash for surface in loaded.surfaces)
    assert any("duplicate surface id" in warning for warning in loaded.warnings)
    assert any("malformed annotation block" in warning for warning in loaded.warnings)

    index_copy = tmp_path / "index.json"
    write_index(loaded, index_copy)
    copied = load_index(index_copy)

    assert copied == loaded


def test_expected_index_fixture_has_the_documented_schema() -> None:
    payload = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))

    assert set(payload) == {"root", "surfaces", "warnings"}
    assert all(set(surface) == {"depends_on", "file", "hash", "id", "invariants", "line_end", "line_start", "modes", "roles"} for surface in payload["surfaces"])
