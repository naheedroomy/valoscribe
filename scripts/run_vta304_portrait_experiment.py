#!/usr/bin/env python3
"""Run the explicitly opt-in local VTA-304 raw portrait experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from valoscribe.tracking.portrait_experiment import run_portrait_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    result = run_portrait_experiment(args.source_root, args.output_dir, args.review)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
