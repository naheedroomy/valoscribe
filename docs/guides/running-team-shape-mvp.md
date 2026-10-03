# Run the offline team-shape MVP

This workflow samples only manually configured source intervals. It does not discover rounds, identify players, or infer missing detections. Deterministic movement summaries describe observed candidates only. Generated media and run data stay under ignored `.local/`.

## Configuration

Use `configs/examples/ascent-team-movement.example.yaml` as JSON-compatible YAML. Copy it to `.local/configs/`, then set a fresh run ID, the source path and matching SHA-256. Keep local video/config/output data under ignored `.local/`. The checked-in example has source-specific candidate calibration values, not a universal profile: inspect the selected VOD and replace/confirm its broadcast crop, orientation, transform and color ranges from that source before analysis. Keep broadcast crop/color settings in the run configuration and zone polygons/assignment limits in `configs/maps/ascent.yaml`.

Example fresh local setup (the example must still be edited for the local video and hash):

```bash
mkdir -p .local/configs
cp configs/examples/ascent-team-movement.example.yaml .local/configs/ascent-local.yaml
# Edit .local/configs/ascent-local.yaml, then:
uv run --extra parquet python -m valoscribe tactical inspect --config .local/configs/ascent-local.yaml
uv run --extra parquet python -m valoscribe tactical analyze --config .local/configs/ascent-local.yaml
```

Choose a never-before-used run ID. `analyze` will not overwrite an existing run. For corrections, use the review/adjudication commands on the local run and rebuild only derived reports with `uv run --extra parquet valoscribe tactical rebuild --run-dir .local/runs/<run-id>`.

The five checked intervals are partial source windows with their live starts included. Round 9 has an explicit replay/transition gap from 971–975 seconds; its first usable opening sample is 975 seconds. The opening window counts usable samples, not excluded gaps.

## Inspect and analyze

```bash
uv run --extra parquet python -m valoscribe tactical inspect \
  --config .local/configs/ascent-team-movement-mvp001.yaml
uv run --extra parquet python -m valoscribe tactical analyze \
  --config .local/configs/ascent-team-movement-mvp001.yaml
```

`inspect` verifies dimensions and hashes, then produces crop, transform, and zone artifacts without marker/tactical claims. `analyze` refuses to overwrite `.local/runs/<run_id>/`, processes only configured intervals at the configured low rate, and writes raw observations, coverage rows, occupancy CSV/Parquet, per-round preview and summary JSON/Markdown, and a manifest. Aggregate JSON/Markdown, pattern CSV, and representative-round JSON are written under `aggregate/`. Choose a new run ID to rerun after review; do not remove prior evidence to reuse a name.

## Interpret output cautiously

HSV components are source-tuned candidates, not validated detections. A color component does not identify a player. Candidate frames remain `partial` until reviewed; zero candidates are `unknown`, not evidence that a team member is absent. Cropped coordinates are retained if an affine result is out of bounds. Black map background, polygon gaps, overlapping interiors, and points within the configured zone boundary tolerance resolve to `unknown` / `OTHER`.

The reviewed status `manually_reviewed_agent_candidate` records parent-agent visual inspection only. It is neither human/user approval nor official geometry nor a quantitative registration accuracy claim. The final user review remains pending.

Playback and calibration artifacts are local. Inspect the minimap playback and canonical overlay at the beginning, middle, and end of each interval, and retain notes on false positives, missed markers, obstructions, and unknown coverage before considering the detector useful.
