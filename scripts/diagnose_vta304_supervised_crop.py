#!/usr/bin/env python3
"""Run a frozen, supervised crop-space VTA-304 diagnostic; never score predictions."""

from __future__ import annotations

import argparse
from pathlib import Path

from valoscribe.tracking.supervised_crop_diagnostic import run_supervised_crop_diagnostic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--hud-config", type=Path, required=True)
    parser.add_argument("--color-profile", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True, help="development-only JSON seed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    args = parser.parse_args()
    result = run_supervised_crop_diagnostic(
        source_path=args.video,
        hud_config_path=args.hud_config,
        color_profile_path=args.color_profile,
        seed_path=args.seed,
        output_path=args.output,
        start_timestamp_s=args.start,
        end_timestamp_s=args.end,
    )
    print(f"Frozen crop-space diagnostic: {result}")


if __name__ == "__main__":
    main()
