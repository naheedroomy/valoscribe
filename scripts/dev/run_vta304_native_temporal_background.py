#!/usr/bin/env python3
"""Run an authenticated native-crop temporal-background diagnostic for VTA304."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from valoscribe.tracking.native_temporal_background import run_native_temporal_background


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run_native_temporal_background(args.source_root, args.output_dir)
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
