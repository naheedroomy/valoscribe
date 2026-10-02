#!/usr/bin/env python3
"""Score only VTA-304 predictions with exact decoded-raster correspondence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from valoscribe.tracking.crop_diagnostic_evaluation import evaluate_crop_diagnostic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_crop_diagnostic(args.run, args.fixture)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(f"Crop diagnostic evaluation: {result['status']} ({args.output})")


if __name__ == "__main__":
    main()
