#!/usr/bin/env python3
"""Opt-in local-only re-decode and hash verification for player labels."""

from __future__ import annotations

import argparse
from pathlib import Path

from valoscribe.analytics.player_identity_observation import verify_identity_observation
from valoscribe.types.player_identity_observation import PlayerIdentityObservation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True, help="authorized local source VOD")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/player_identity_observation_vta304_round4.json"),
    )
    args = parser.parse_args()
    observation = PlayerIdentityObservation.model_validate_json(args.manifest.read_text())
    verify_identity_observation(args.video, observation)
    print(f"verified {len(observation.samples)} source identity samples")


if __name__ == "__main__":
    main()
