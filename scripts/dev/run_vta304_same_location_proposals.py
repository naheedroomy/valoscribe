#!/usr/bin/env python3
"""Replay the pinned VTA-304 crop packet as raw same-location proposals."""

from __future__ import annotations

import argparse
from pathlib import Path

from valoscribe.tracking.same_location_proposal import run_same_location_proposal_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--readback-root",
        type=Path,
        default=Path("/private/tmp/vta304-round4-neutral-portrait-experiment-v3-readback"),
    )
    args = parser.parse_args()
    manifest = run_same_location_proposal_diagnostic(
        args.source_root,
        args.output_dir,
        readback_root=args.readback_root,
    )
    print(manifest.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
