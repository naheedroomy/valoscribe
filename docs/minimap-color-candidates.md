# Minimap broadcast-color candidates

> **Local/future-checkpoint note:** The detector, profile, evaluator, and tests cited here are not included in a docs-only published checkout until a dependency-complete code checkpoint is included. Recipes are not runnable from docs alone; see [`PUBLISH_BOUNDARY.md`](PUBLISH_BOUNDARY.md).

`MinimapColorCandidateDetector` emits raw color-mask contours from a cropped
minimap. It accepts per-profile HSV intervals and morphology/shape thresholds;
it does not assign a player, team, attack/defense side, or identity. HSV bounds
use OpenCV units (H 0–179; S/V 0–255). A configured color such as `teal` or
`red` is only a broadcast-color label.

## VTA-201 reviewed measurement

`docs/minimap_color_review_vta201.json` contains two independently visually
reviewed 360x400 crops from the Ascent VCT Americas Stage 2 Grand Final VOD.
The corrected training sample has six manually confirmed icon centers and the
held-out sample retains all seven previously reviewed centers. Both include
source frame/timestamp, crop provenance, and a SHA-256 of decoded OpenCV BGR
pixel bytes. Coordinates were reviewed to approximately ±2 px. Temporal review
of frames 300–303 found the red mark at (75,202) overlapped a static dark mark
and moving red icon; the mark is not called a live player and is excluded by the
inclusive ignore box [68,194,85,211]. Identity remains unresolved. Temporal
review of frames 838–843 confirmed all seven 840s positives. The unresolved
dark circle near (256,263) remains ignored in both frames using the inclusive
box [247,254,265,272]. These boxes exclude candidate centers and labels without
classifying their contents. The other yellow spike/glyph marks are not player
labels.

Only frame 300 (source frame 18000) was used to fit the profile. Frame 840
(source frame 50400) was held out and was not used for profile adjustment. The
frozen, tournament/HUD-specific profile is
`src/valoscribe/config/minimap_color_vta201_train_profile.json`; it is not a map
configuration and its broadcast colors do not represent attack or defense.
The selected training-grid profile uses 8 px one-to-one center matching.
Reproduce the scored result and write overlays/diagnostics with:

```bash
uv run python scripts/evaluate_minimap_color_vta201.py \
  --output-dir /tmp/vta201-minimap-color
```

By default the script reads the exact crops from the manifest's local artifact
paths. If these files are absent, it exits with a clear error; no images or VOD
pixels are bundled. To use the original local VOD instead, provide
`--video /path/to/original.mp4`; extraction uses source frame indices and the
manifest crop rectangle, then checks decoded crop hashes. Alternatively,
`--crops-dir DIR` reads `calibration-300.png` and `calibration-840.png` there.
Hash or dimension mismatches fail the run. Each frame gets an accepted-green /
rejected-red candidate overlay and `evaluation.json` records split metrics,
counts, matched distances, every unmatched accepted candidate (false positive),
and every unmatched reviewed center (false negative).

With the unchanged frozen profile at an 8 px match tolerance, the corrected
training frame 300 scores 3 TP / 10 FP / 3 FN (precision 0.231, recall
0.500), and held-out frame 840 scores 7 TP / 23 FP / 0 FN (precision 0.233,
recall 1.000). The revised training score reflects only demoting the ambiguous
(75,202) review label; the held-out labels and profile were not retuned. The high
false-positive count means this measured candidate detector does **not** meet
a useful precision target; these two frames are a minimal acceptance sample,
not evidence of generalization to other tournaments, HUD styles, maps, or
conditions. Do not interpret the heuristic confidence as a probability. Further
threshold tuning requires additional labeled training frames and a new untouched
held-out split.

The raw `RawMinimapColorCandidate` contract retains accepted and rejected
contours with normalized center/bounds, area, mask pixel count, confidence,
source timestamp/frame, configured color, and rejection reasons. Synthetic
tests cover mask/shape filtering, exclusion regions, one-to-one matching,
ignore boundaries, provenance hashes/dimensions, and overlays. `excluded_background`
is available for separately validated static/obstructed pixel masks; it is not
inferred from player labels.
