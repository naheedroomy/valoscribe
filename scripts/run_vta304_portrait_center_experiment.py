#!/usr/bin/env python3
"""Run the frozen two-frame VTA-304 portrait-center feasibility experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from valoscribe.tracking.portrait_center_experiment import run_portrait_center_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--method", choices=("radial", "contour"), default="radial")
    args = parser.parse_args()
    report = run_portrait_center_experiment(
        args.source_root, args.fixture, args.output_dir, method=args.method
    )
    print(json.dumps(report["summary"], sort_keys=True))
    print(f"Diagnostic artifacts: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
