# VTA-502: independently reviewed Omen cast evidence (1423.4–1425.4s)

`vta502_cast_observation_1425.json` records one high-confidence **cast identity** observation: continuous 100T bang/Omen targeting and releasing Dark Cover. It is deliberately not a `ReviewedSmokeLabel`. The record separately leaves world deployment, smoke lifecycle, caster-to-footprint correspondence, minimap correspondence, and center unknown. Do not use it as smoke true-positive/ground truth or infer a deployed location from the HUD/cast sequence.

## Reproducing the source evidence

The source VOD is external and is not checked in:

- VOD: `/Users/naheedroomy/Documents/valorant-analyzer/VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`
- VOD SHA-256: `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`
- Independent raw acquisition packet: `/tmp/vta502-cast1425-review/manifest.json` (71 sampled frames, 1421–1428s, 0.1s interval; frame/crop hashes are SHA-256 of decoded row-major uint8 BGR bytes, before image encoding).
- Raw full frames and minimap crops are in the packet's `frames/` and `crops/` directories. Their nine cited frame identifiers, timestamps, and full-frame/crop digests are copied into the JSON record. The original packet and VOD remain required for pixel-level replay; neither is stored in this repository.

## Reviewed sequence and limits

Targeting entry is bracketed 1423.4–1423.5s; the cyan Dark Cover preview is visible 1423.7–1424.8s. In the HUD, both bars are gray before targeting, the left bar is yellow on targeting entry, and that bar changes from yellow to gray during the observed targeting/release transition at 1424.8–1424.9s. The round timer changes from 40 to 39 before release and is not charge-count evidence. An open glove is visible at 1425.0s, world view returns at 1425.1s, and the observer cuts to Vora at 1425.3–1425.4s. The cut limits later caster tracking. This establishes a cast, not absolute charge counts, bar semantics, successful world deployment, destination, minimap mapping, or smoke presence/duration. There is no video fixture checked in; tests use the persisted manifest-derived hashes and synthetic mutation/failure cases.
