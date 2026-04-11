"""Deterministic lexical ranking for query surfaces."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from scoped_control.models import ResolverMatch, SurfaceRecord

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def rank_surface_for_request(surface: SurfaceRecord, request: str) -> ResolverMatch:
    """Score one surface for a free-form request."""

    request_lower = request.lower()
    request_tokens = set(_tokenize(request))
    surface_tokens = set(_tokenize(surface.id.replace(".", " ")))
    file_name = PurePosixPath(surface.file).name
    file_stem = PurePosixPath(surface.file).stem
    file_tokens = set(_tokenize(file_stem.replace(".", " ")))
    context_tokens = set(_tokenize(" ".join((*surface.invariants, *surface.depends_on))))

    score = 0
    reasons: list[str] = []

    if surface.id.lower() in request_lower:
        score += 120
        reasons.append(f"surface id `{surface.id}` matched")

    id_overlap = sorted(request_tokens & surface_tokens)
    if id_overlap:
        score += 40 + (10 * len(id_overlap))
        reasons.append(f"surface id keywords: {', '.join(id_overlap)}")

    if file_name.lower() in request_lower or file_stem.lower() in request_lower:
        score += 80
        reasons.append(f"file name `{file_name}` matched")

    file_overlap = sorted(request_tokens & file_tokens)
    if file_overlap:
        score += 20 + (5 * len(file_overlap))
        reasons.append(f"file keywords: {', '.join(file_overlap)}")

    context_overlap = sorted(request_tokens & context_tokens)
    if context_overlap:
        score += 5 * len(context_overlap)
        reasons.append(f"context keywords: {', '.join(context_overlap)}")

    return ResolverMatch(surface=surface, score=score, reasons=tuple(reasons))


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 1)
