from __future__ import annotations

import json

from scoped_control.index.store import load_index, write_index
from scoped_control.models import IndexRecord, SurfaceRecord


def test_write_index_persists_the_expected_surface_shape(tmp_path) -> None:
    index = IndexRecord(
        root=str(tmp_path),
        surfaces=(
            SurfaceRecord(
                id="python.primary",
                file="python_repeated_annotations.py",
                line_start=7,
                line_end=8,
                roles=("maintainer", "reviewer"),
                modes=("query", "edit"),
                invariants=("keep main entry stable",),
                depends_on=("shared.helpers",),
                hash="python-primary-hash",
            ),
            SurfaceRecord(
                id="typescript.primary",
                file="typescript_repeated_annotations.ts",
                line_start=7,
                line_end=9,
                roles=("maintainer",),
                modes=("query", "edit"),
                invariants=("keep main entry stable",),
                depends_on=("shared.helpers",),
                hash="typescript-primary-hash",
            ),
        ),
        warnings=("duplicate surface id: shared.duplicate",),
    )
    index_path = tmp_path / "index.json"

    write_index(index, index_path)
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    assert payload["root"] == str(tmp_path)
    assert payload["warnings"] == ["duplicate surface id: shared.duplicate"]
    assert len(payload["surfaces"]) == 2
    assert set(payload["surfaces"][0]) == {"depends_on", "file", "hash", "id", "invariants", "line_end", "line_start", "modes", "roles"}
    assert payload["surfaces"][0]["id"] == "python.primary"
    assert payload["surfaces"][0]["line_start"] == 7
    assert payload["surfaces"][0]["line_end"] == 8
    assert payload["surfaces"][0]["roles"] == ["maintainer", "reviewer"]
    assert payload["surfaces"][0]["depends_on"] == ["shared.helpers"]


def test_load_index_round_trips_the_full_contract(tmp_path) -> None:
    index_path = tmp_path / "index.json"
    write_index(
        IndexRecord(
            root=str(tmp_path),
            surfaces=(
                SurfaceRecord(
                    id="plain.primary",
                    file="plain_text_repeated_annotations.txt",
                    line_start=7,
                    line_end=7,
                    roles=("maintainer",),
                    modes=("query",),
                    invariants=("preserve exact wording",),
                    depends_on=("reference.guide",),
                    hash="plaintext-primary-hash",
                ),
            ),
            warnings=("malformed annotation block missing surface id",),
        ),
        index_path,
    )

    loaded = load_index(index_path)

    assert loaded.root == str(tmp_path)
    assert loaded.warnings == ("malformed annotation block missing surface id",)
    assert loaded.surfaces[0].id == "plain.primary"
    assert loaded.surfaces[0].file == "plain_text_repeated_annotations.txt"
    assert loaded.surfaces[0].line_start == 7
    assert loaded.surfaces[0].line_end == 7
    assert loaded.surfaces[0].roles == ("maintainer",)
    assert loaded.surfaces[0].modes == ("query",)
    assert loaded.surfaces[0].invariants == ("preserve exact wording",)
    assert loaded.surfaces[0].depends_on == ("reference.guide",)
    assert loaded.surfaces[0].hash == "plaintext-primary-hash"
