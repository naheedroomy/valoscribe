from __future__ import annotations

import pytest
from pydantic import ValidationError

from valoscribe.types.anonymous_report import AnonymousRoundInput
from valoscribe.types.anonymous_tracking import AnonymousFrameContext, AnonymousRoundBounds


def _bounds() -> AnonymousRoundBounds:
    return AnonymousRoundBounds(
        map_number=1,
        round_number=1,
        map_id="ascent",
        start_frame_index=10,
        end_frame_index=12,
        start_source_pts=100,
        end_source_pts=120,
        reviewer_id="reviewer",
        evidence_reference="review.json#bounds",
        review_status="externally_reviewed",
    )


def _context(index: int) -> AnonymousFrameContext:
    return AnonymousFrameContext(
        frame_index=index,
        state="unknown",
        reviewer_id="reviewer",
        evidence_reference=f"review.json#frame-{index}",
        review_status="externally_reviewed",
    )


def test_anonymous_round_input_preserves_unreviewed_context_as_omitted() -> None:
    result = AnonymousRoundInput(bounds=_bounds(), context_by_frame=(_context(10),))
    assert result.context_by_frame[0].state == "unknown"
    assert len(result.context_by_frame) == 1


def test_anonymous_round_input_rejects_duplicate_or_out_of_bounds_context() -> None:
    with pytest.raises(ValidationError, match="duplicate frame indices"):
        AnonymousRoundInput(bounds=_bounds(), context_by_frame=(_context(10), _context(10)))
    with pytest.raises(ValidationError, match="outside externally reviewed bounds"):
        AnonymousRoundInput(bounds=_bounds(), context_by_frame=(_context(13),))
