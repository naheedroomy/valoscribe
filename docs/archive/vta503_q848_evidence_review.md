> **Archived:** Historical material retained for provenance; it is not current implementation guidance. Use the [active MVP Reset specification](../../specs/active/MVP_RESET_AND_REPOSITORY_CLEANUP_SPEC.md).

# VTA-503 Q848 bounded evidence review

## Scope and provenance

This is a documentation-only review of the single 848.000–854.000 s interval in the supplied VOD. It does not modify production code, schemas, tests, or the prior raw HUD-observation JSON, and it does not reinterpret the earlier Omen evidence. The temporary packet is supporting review material, not a permanent fixture.

- Source: `/Users/naheedroomy/Documents/valorant-analyzer/VOD/YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`
- Exact source SHA-256: `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`
- Video dimensions/rate: 1920×1080, 60 fps.
- Bounded decode: 361 sequential frame indices, 50880–51240 inclusive (848.000–854.000 s); no sequential decode errors reported.
- Sample packet: 73 full frames and 146 crops. The parent verified those fullframes and crops by matching BGR hashes against sequential source decode. This review relies on that verification; it did not independently recompute the hashes.
- Packet: `tmp/vta503-q848-packet-v2/manifest.json` and its `frames/` and `crops/` children. The packet is temporary/untracked and must not be treated as durable fixture storage.

Manifest crop rectangles, in source pixels, were `[480, 780, 960, 300]` (`q_adjacent_slots`) and `[480, 740, 960, 170]` (`portrait_label`). These measured rectangles are exploratory review crops only—not production HUD coordinates or calibration.

## Native anchor provenance and reviewed observations

Paths below are relative to `tmp/vta503-q848-packet-v2/`. SHA-256 values are exact decoded BGR hashes from the manifest; the PNG-roundtrip BGR hashes match those values. Frame time is source index / 60 fps.

| Native frame | Index / time | Full decoded-BGR SHA-256 | Review finding |
|---|---:|---|---|
| `frames/frame-001-idx-50880.png` | 50880 / 848.000 s | `3e0ea66ebc147a59b3ab9a624de92dab392922b242e1bd9ee8d95844ecf4ed31` | LOUD tkzin, recognizable Neon portrait/ability set; knife; broad turquoise Q strip. |
| `frames/frame-025-idx-51000.png` | 51000 / 850.000 s | `820627a677511b35f031dc6381d5f2ac9228c08d474696b601b6eacb47d863ba` | Same player; glowing hands; Q turquoise. Broadcast banner reads **100T Asuna PLANTING**, not replay. |
| `frames/frame-031-idx-51030.png` | 51030 / 850.500 s | `aa5dbf6f25db3c6bb9f81d61e5f231001d481d67d7321ec71b612bb90c79eb2a` | Forward hand/energy action; partial HUD occlusion. |
| `frames/frame-032-idx-51035.png` | 51035 / 850.583333 s | `149a84895747486f7928467124009f5ecdfd27cc259b2782cb58d0e75af057b5` | Continued cyan/yellow hand-action sequence. |
| `frames/frame-033-idx-51040.png` | 51040 / 850.666667 s | `a2cb71d879101dc24b277ecf4a23e078abd76ac2e53720803c329039097388be` | Q strip visibly gray; probable Relay Bolt release sequence, not calibrated inventory loss. |
| `frames/frame-057-idx-51160.png` | 51160 / 852.666667 s | `3c764d752cc1c10cb4c3991b90cac268f9c39e8ba36c7848a9729aadb1bcd7d3` | Settled rifle 25/60; Q and C gray; adjacent display 12. |
| `frames/frame-062-idx-51185.png` | 51185 / 853.083333 s | `6cd54a0dfbad1ce1f8561770335657e51851ca4aafa432e380be77530a3e4bef` | tkzin/Neon at A Window; rifle 24/60; gray Q; SPIKE PLANTED. |
| `frames/frame-063-idx-51190.png` | 51190 / 853.166667 s | `7181928acdab06ff8015f41a7a83de230a795891fda22446307ba6a0dd41e588` | Observer switches to LOUD Darker/Phoenix at A Lobby, health 100; facecam briefly still labels tkzin. |
| `frames/frame-064-idx-51195.png` | 51195 / 853.250 s | `10096acaa98a595d67893c070193c8a1af49cba41e4722cbabc87a274a4d4fa5` | Darker/Phoenix persists; facecam catches up. |

The observer cut is bracketed by indices **51185–51190**; no exact transition frame is established. Q is turquoise in the reviewed early anchor(s), hand-occluded during frames 031–032, and clearly gray by frame 033. This does not establish an exact first-change frame. The PLANTING banner is positive evidence against a replay interpretation, but there is no independent certification that the reviewed sequence is LIVE.

Crop path/hash spot references: `crops/q_adjacent_slots-frame-025-idx-51000.png` has decoded-BGR SHA-256 `94f1fa497d3bd0975417c99e5adcebcba1072d7a2ed2448ac1af2aa0e28ef9d6`; `crops/q_adjacent_slots-frame-057-idx-51160.png` has `636ff813d58fd5342a97e4c8aa0e885fb290776f95bf40bb7ec1ec3f7c1405bc`. They show broad turquoise and gray states, respectively, not countable units.

## Bounded outcome

- Independently reviewed player/ability context supports tkzin/Neon and a broad Q-strip transition toward gray, with a probable cast/release sequence. Cast evidence and HUD state remain separate observations.
- Before/after inventory counts are **UNKNOWN**. There is **no accepted charge decrement**. A color/fill change does not establish `1 → 0` or any other integer delta.
- Verified countable symbols could support counts without OCR, if the unit-to-inventory semantics and endpoints were independently calibrated. No such calibration is present here; do not substitute inferred counts.
- Cast identity, HUD charge evidence, and spatial utility association remain separate. This review does not establish spatial association, compatible identity/timing confidence, or association uncertainty.
- Required same-HUD external controls are absent: verified non-recharging multi-use ability with known initial inventory/equip-cancel, two separate actual uses and settled states, depletion, and reset/purchase control. The user confirms this is the only available current VOD. Do not launch an endless local rescan; request the specified external calibration artifact if that evidence is pursued later.
- VTA-503 REAL acceptance remains **OPEN**. Preserve the existing acceptance criteria, including spatial association, compatible identity/timing confidence and uncertainty, and the outstanding VTA-502 metrics. This bounded packet does not satisfy those gates.

## Reproducibility limitation

The exact source digest, interval indices, and anchor BGR hashes are recorded above for traceability. The temporary packet is not permanent fixture storage; this note does not claim that another reviewer can reproduce image-level judgments from a retained fixture. The parent’s BGR/hash verification is recorded as provenance, not represented as this reviewer’s independent recomputation.
