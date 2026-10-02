from __future__ import annotations

import pytest
from pydantic import ValidationError

from valoscribe.types.anonymous_tracking import AnonymousRoundBounds


def _bounds(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "map_number": 1,
        "round_number": 4,
        "map_id": "synthetic-map",
        "start_frame_index": 2,
        "end_frame_index": 8,
        "start_source_pts": 40,
        "end_source_pts": 160,
        "reviewer_id": "synthetic-fixture-reviewer",
        "evidence_reference": "synthetic-fixture-frame-index-list-v1",
        "review_status": "externally_reviewed",
    }
    values.update(overrides)
    return values


def test_bounds_require_external_review_and_inclusive_ordered_bounds() -> None:
    bounds = AnonymousRoundBounds.model_validate(_bounds())
    assert bounds.end_frame_index == 8
    with pytest.raises(ValidationError):
        AnonymousRoundBounds.model_validate(_bounds(review_status="pending"))
    with pytest.raises(ValidationError, match="reversed"):
        AnonymousRoundBounds.model_validate(_bounds(end_frame_index=1))


def test_tracklet_contract_does_not_allow_player_identity_fields() -> None:
    allowed = set(AnonymousRoundBounds.model_fields)
    assert "player_id" not in allowed
    assert "team_id" not in allowed
    assert "side" not in allowed
