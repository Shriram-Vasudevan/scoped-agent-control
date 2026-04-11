from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wave2"


@pytest.mark.parametrize(
    ("path", "prefix", "expected_targets"),
    [
        (
            FIXTURES / "python_repeated_annotations.py",
            "#",
            ("def primary_handler():", "def secondary_handler():"),
        ),
        (
            FIXTURES / "typescript_repeated_annotations.ts",
            "//",
            ("export function primaryHandler(): string {", "export function secondaryHandler(): string {"),
        ),
        (
            FIXTURES / "plain_text_repeated_annotations.txt",
            "#",
            ("Plain text body paragraph one.", "Plain text body paragraph two."),
        ),
    ],
)
def test_repeated_line_fixtures_attach_to_the_next_content_line(path: Path, prefix: str, expected_targets: tuple[str, ...]) -> None:
    lines = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines()]

    annotation_blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            current_block.append(line)
            continue
        if current_block:
            annotation_blocks.append(current_block)
            current_block = []
    if current_block:
        annotation_blocks.append(current_block)

    assert len(annotation_blocks) == 2
    assert all(block and all(line.startswith(prefix) for line in block) for block in annotation_blocks)
    for target in expected_targets:
        assert target in lines
    for block, target in zip(annotation_blocks, expected_targets, strict=True):
        target_index = lines.index(target)
        assert target_index > lines.index(block[-1])
        assert target_index == next(index for index, line in enumerate(lines) if line == target)


def test_malformed_and_duplicate_fixture_encodes_warning_cases() -> None:
    lines = [line.rstrip("\n") for line in (FIXTURES / "malformed_and_duplicate.py").read_text(encoding="utf-8").splitlines()]

    assert lines.count("# surface: shared.duplicate") == 2
    malformed_block_start = lines.index("# roles: maintainer", lines.index("# surface: shared.duplicate", 1))
    malformed_target = lines.index("def malformed_block():")

    assert malformed_block_start < malformed_target
    assert "# surface:" not in lines[malformed_block_start:malformed_target]
