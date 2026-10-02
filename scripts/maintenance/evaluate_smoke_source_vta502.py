#!/usr/bin/env python3
"""Exploratory, source-only VTA-502 replay; not production detector validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from valoscribe.analytics.smoke_source_vta502 import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True, help="local authorized source VOD")
    parser.add_argument(
        "--manifest", type=Path, default=Path("docs/smoke_source_observation_vta502.json")
    )
    parser.add_argument("--output", type=Path, help="optional JSON results path")
    args = parser.parse_args()
    results = evaluate(args.video, args.manifest)
    encoded = json.dumps(results, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
