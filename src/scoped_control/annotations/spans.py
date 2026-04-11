"""Surface span inference heuristics."""

from __future__ import annotations

from typing import Sequence


def infer_surface_span(lines: Sequence[str], start_index: int, stop_index: int) -> int:
    """Infer the annotated block end using simple indentation and blank-line heuristics."""

    base_indent = _indentation(lines[start_index])
    last_non_blank = start_index
    bracket_depth = _bracket_delta(lines[start_index])

    index = start_index + 1
    while index < stop_index:
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            next_non_blank = _find_next_non_blank(lines, index + 1, stop_index)
            if next_non_blank is None:
                break
            if bracket_depth <= 0 and _indentation(lines[next_non_blank]) <= base_indent:
                break
            index += 1
            continue

        if bracket_depth <= 0 and _indentation(line) < base_indent:
            break

        bracket_depth += _bracket_delta(line)
        last_non_blank = index
        index += 1

    return last_non_blank


def _find_next_non_blank(lines: Sequence[str], start: int, stop: int) -> int | None:
    for index in range(start, stop):
        if lines[index].strip():
            return index
    return None


def _indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _bracket_delta(line: str) -> int:
    opens = sum(line.count(ch) for ch in "([{")
    closes = sum(line.count(ch) for ch in ")]}")
    return opens - closes
