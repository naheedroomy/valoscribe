# MVP-001 calibration candidate — pending review

This is a source-backed, manually measured candidate, not an accepted calibration or product result. RST-001/RST-002 are accepted separately; MVP-001's human visual review gate remains open.

## Source and source-specific interpretation

- Local source: `../VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4` (not copied into the repository).
- SHA-256: `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`.
- Verified video: 1920×1080, 60 fps.
- Selected source team/side: 100 Thieves (100T), attack, first half. This is specific to the reviewed broadcast and does not imply a persistent color-to-side mapping.
- Source-specific minimap crop: x=70, y=50, width=360, height=400; candidate crop hashes at t=300 and t=840 agree with prior reviewed raw crops. Candidate orientation is 90° CCW.

## Selected, partial source intervals

The windows include each selected round's opening; none is claimed to be a complete round. The opening window is the first 8 **usable** seconds after the configured live start; excluded replay samples are explicit gaps and do not count toward it. R9 has source interval 971–1020 with a 971–975 excluded replay/transition gap, so usable opening evidence begins at t=975.

| Round | Interval (s) | Opening evidence / selection rationale | Known review concern |
|---|---:|---|---|
| R4 | 263–330 | t=262 shows pre-round 0:00; t=263 shows live 1:39 | overlap/dark marker ambiguity near t=300; spike-carrier-killed banner |
| R5 | 379–420 | t=378 shows pre-round 0:00; t=379 shows live 1:40; t=390 shows 1:28 | bright background/ability visibility concern near t=405 |
| R6 | 540–600 | t=539 shows pre-round 0:00; t=540 shows live 1:39 | partial window includes plant sequence |
| R7 | 790–870 | t=789 shows pre-round 0:00; t=790 shows live 1:39 | partial window includes plant sequence |
| R9 | 971–1020 | t=971–974 replay/transition (excluded); t=975 first live frame at 1:39 | partial window; R8 omitted because broadcast transitions to crowd/desk around t=930 |

These intervals are source-verified partial windows, not full-round discovery. The three-frame-per-window source contact is `.local/runs/mvp001/calibration/opening-start-contact.jpg`; existing 15-frame full-source and crop contacts are `.local/runs/mvp001/calibration/revised-five-interval-full-contact.jpg` and `.local/runs/mvp001/calibration/revised-five-interval-crop-contact.jpg` (beginning/middle/end of the revised windows).

## Candidate transform

The canonical Riot Ascent asset is the existing 2048×2048 `src/valoscribe/config/maps/ascent_public_content_13_06.png`, SHA-256 `6094459e109b1f4e9d500277ebc4ce1392dd98fb4f2d92005be932105be8a593`. The candidate raw-crop-pixel → canonical-pixel affine matrix is:

```text
[[-0.0326733681,  4.9397239044,   48.6174636631],
 [-4.9208259748, -0.0087414481, 1902.8049429962]]
```

It was fitted from 10 approximate visual training correspondences (mean/RMS/max residual 1.1604/1.3662/2.4751 px). Approximate held-out maxima were 9.1376 px at t=2460 and 7.2684 px at t=2820 and t=2940. The landmarks are not ground-truth measurements; these residuals do not establish canonical accuracy. The cleanly floorplan-masked candidate overlay contact is `.local/runs/mvp001/calibration/selected-five-windows-transform-masked-contact.jpg`; the earlier unmasked transform contact is retained for comparison.

## Manually authored candidate zones

`configs/maps/ascent.yaml` contains 14 manually digitized, labeled candidate regions corresponding to the required Ascent areas. Coordinates were traced approximately from external labeled overview `/tmp/vta102-ascent-community-overview.png` (SHA-256 `c62eea459c56980bf751bdecb0583f6a02da72095251c09fe74b5e4b4caccb1a76`), then transformed into canonical asset pixels using the recorded overview-to-canonical affine. The external image is not redistributed. `Unknown / outside configured polygons` is an explicit `OTHER` fallback, not an invented polygon.

The full-size rendered overlay is `.local/runs/mvp001/calibration/ascent-zone-candidate-overlay.png`. The parent agent visually inspected this overlay and the labeled reference grid and considers source-grounded approximate zones plausible for manual team-shape development. This is not human/user approval or official geometry. Touching boundaries, gaps, and black space remain unknown/OTHER; any tie resolution must be deterministic. User final review is separate and pending. The conventional source labels Mid Bottom and Mid Top are retained, with source orientation clarified: Mid Bottom is toward defenders and Mid Top is near attackers. Macro group remains MID for both.

## Candidate config and calibration status

- Redacted tracked example: `configs/examples/ascent-team-movement.example.yaml`.
- Machine-specific ignored config: `.local/configs/ascent-team-movement-mvp001.yaml`.
- Both configs mark transform/color parameters as candidates, retain the source hash, contain all five opening-inclusive intervals, and avoid claiming detection results. HSV values are unaccepted candidate thresholds; prior two-frame precision was adverse.
- MVP-001 calibration gate: **parent-agent visual inspection complete for manual team-shape development**. This was parent-agent review, not human/user approval or official geometry. The map records that distinction and preserves black space, gaps, and ambiguous boundaries as unknown/OTHER with deterministic assignment required. No quantitative registration accuracy is claimed; user final review remains separate. No detector, five-round processing, corrections, or tactical summaries were added in the MVP-001 gate-close commit.
