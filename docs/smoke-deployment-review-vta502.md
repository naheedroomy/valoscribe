# VTA-502 bounded deployment evidence review

**Status: documentation closeout only; VTA-502 is not complete.** This is an independent, bounded visual observation of raw source frames. It is not detector output, a canonical smoke label, a deployment result, or acceptance evidence for precision/recall or timing metrics. No thresholds were tuned and no predictions were reviewed.

## Provenance and review scope

Both acquisition manifests identify the source video as `YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`. The cast-review manifest at `/tmp/vta502-cast1795-review/manifest.json` supplies `source_video_sha256`; the deployment-gap manifest at `/tmp/vta502-deployment-gap-review/manifest.json` supplies `source_video_file_sha256`. Both report SHA-256 `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44`, recomputed from the local video file and matched to each manifest's respective field. The source-frame acquisitions and their unannotated crops are local review artifacts, not checked-in pixels:

- `/tmp/vta502-deployment-gap-review/manifest.json` (`VTA502_BOUNDED_RAW_EVIDENCE_ACQUISITION`): 42 frames in ranges 108286–108299, 108301–108314, and 108316–108329, with a fixed crop at `(x=70, y=50, width=360, height=400)`.
- `/tmp/vta502-cast1795-review/manifest.json` (`VTA502_DENSE_RAW_SOURCE_FRAME_ACQUISITION`): 81 frames sampled every 0.25 seconds across 1792–1812 seconds, with the same fixed crop.

Times below are **nominal frame index / 60** (nominal 60 fps), not independently established presentation timestamps. Manifest pixel hashes are SHA-256 over contiguous decoded BGR bytes; PNG-file hashes are SHA-256 over encoded file bytes. These are different hash domains. The source-video digest and every cited frame/crop file and decoded crop-BGR hash below were recomputed from local files and matched their respective manifest values. For the main-world observations, the separate table also gives full-frame encoded-file and decoded-BGR hashes; crop-only hashes cannot substantiate those observations.

| Nominal time | Frame | Crop PNG file SHA-256 | Decoded crop BGR SHA-256 |
| --- | ---: | --- | --- |
| 1804.916667 s | 108295 | `1f5f96d2139fb69b4de7ebe5ee44e746ea2b26d0a63f4715b463da1c7fc71214` | `e01c8bcdd9305d87510e8fe3f8a5f772a6d56fe525fda241bbac490d53c54154` |
| 1805.083333 s | 108305 | `888e761b719e14340b5497389dba57dff4a38071cd1fd78b159fdbc1035945b5` | `460d63defc903bacab937afd562847a67987b30d6d7b9bde5d4fb2890cfa786c` |
| 1805.166667 s | 108310 | `ce6ef8328297a919a213edecee0937ca194d1510a52b3122b5edde28dbb5f75e` | `2488da736ecdbcd85e2e1ae52ba14848285d459b0d7293d2cdf4bda26abfd730` |
| 1805.183333 s | 108311 | `838cbb1e2d5d13a14472bf77991a15f068eeeda4aafd732ea7badd8d04047f24` | `c2b92fd794153f2b606c1d258c5eb8bf85540255ce593229c136b7c081c7f15d` |
| 1805.483333 s | 108329 | `cfab74a87132155e9f54ab19ff7ab76a97e9f1d13f86c0f1ffdad44ed6c3e979` | `541f89f5e9e8c761eafd7f3763845b9e87369d52c8af13713945d994e207782d` |
| 1809.000000 s | 108540 | `d9883b33a6c8dbc6875a115d15867542cbc75f839609e54fd92afcb1322d222d` | `39a48d2d7f384bc7d0a8884d0bd8f79caf22d01253e1fdc43bdac8b74d7fda0f` |

The adjacent acquired ranges contain the other frames in the cited intervals; the full per-frame manifest records their filenames and hash values. A successful digest check establishes that these local files match the manifests, not that a visual interpretation is correct.

For the world-view observations, the cited full-frame hashes are:

| Nominal time | Frame | Manifest / frame file | Full-frame PNG file SHA-256 | Decoded full-frame BGR SHA-256 |
| --- | ---: | --- | --- | --- |
| 1804.916667 s | 108295 | deployment-gap / `frames/frame_f108295.png` | `e71c830790017c65b92ce5353e6b62c4cfcacc79e94bdd6a7ac462f4d4612a17` | `154759610a9c69eda36388447414fe0c49755e892d616d2c86468d1c41d04788` |
| 1805.000000 s | 108300 | cast-review / `frames/frame_1805.00s_f108300.png` | `6f0d23eddd73c7681150c58f382bd8bbfae356657af1cc39f4dcd052498be2ec` | `8a647c609a865c375abdadc17b668034ed5748e769563fa7851c7f0cf056e7fd` |
| 1805.166667 s | 108310 | deployment-gap / `frames/frame_f108310.png` | `074dbac3cdd5aad9fa7aaf68f059557714d32442675a7ccb88e9902ad54e4eec` | `af6434cfc2b0bff33dc1fa899043f5de6fbb77df3b8604b7c27a2add51fe6bd7` |
| 1805.183333 s | 108311 | deployment-gap / `frames/frame_f108311.png` | `4a68719ec4486f8bdb01e135628bf2344b5f9eadb716a58454ff5cdce3bdae43` | `8e70eed85030c3d1fdf8f941fa2ff58885d616f5c893de56a77afa326e038833` |
| 1805.250000 s | 108315 | cast-review / `frames/frame_1805.25s_f108315.png` | `67b6d74c67ba04031542954d3751b2230300ad9ae8fdaef9d62d08aa5413e178` | `4d82d18f429e54b8d93d810dc64a1d43ad769d4006caf01e97d7efd975f243f8` |

## Independent observations

- **Ability/type evidence:** the separately recorded observer comparison is foreground frame 108315 (nominal 1805.25 s) versus generator frame 108300 (1805.00 s). Omen Dark Cover identification at **95% subjective observer confidence** is based on the foreground animated banded opaque spherical shell and hollow interior, not purple color alone or roster inference. This supports an ability/agent-type observation only; it does not establish which Omen player cast it.
- **Roster context:** the ten-agent HUD roster showed LOUD: Chamber, Sova, Neon, Omen, Phoenix; 100T: Phoenix, Cypher, Omen, Sova, Jett. That roster was observed at nominal frames 107715 (1795.25 s) and 108315 (1805.25 s). A roster-only type guess is outside the independently observed supported-evidence gate and cannot attribute a smoke. Player association remains `UNKNOWN` and is reserved for VTA-503.
- **Separate source/minimap structures:** the generator spiral is observed at frames 108295–108304 (nominal 1804.916667–1805.066667 s), including generator-reference frame 108300. The resolved Tree-entry dome expansion begins at frame 108311: it is seen across frames 108311–108314, at frame 108315 in the cast-review packet, and continues across 108316–108329. The dark aperture at frames 108305–108307 is not evidence of entry into that later dome. At frames 108308–108310, seed-like pixels are partly obscured by player labels. The conspicuous expansion is bracketed across 108310→108311; this is **not** an absence-to-presence bracket. Exact onset and disappearance remain `UNKNOWN`.
- **Minimap ring:** a large ring is already present before the observed expansion. Its unique correspondence to the later dome is **UNLINKED (95% subjective observer confidence)**. The source-crop center and uncertainty are `UNKNOWN`; caster/player association is `UNKNOWN`. At nominal 1809.0 s (frame 108540), two domes are visible, but continuity with either earlier structure is not established.
- **Old observation:** this review does not reconcile the disputed circle from the existing 2490-second source-space observation. That historical uncertainty remains as documented in [smoke-detection.md](smoke-detection.md).

These confidence figures are subjective observer assessments for the stated visual judgments, not calibrated probabilities or measured detector confidence. Observed frames and roster context do not establish canonical map coordinates, continuous smoke identity, or a lifecycle interval.

## Boundaries and next evidence

No reviewed canonical labels, detector predictions, prediction-to-observation attribution, held-out cohort, precision/recall, or timing metrics were available or created. This review does not establish that VTA-502 acceptance criteria are met and does not claim full VTA-502 completion. Existing supported-agent gates and unresolved historical metadata are unchanged.

To support a later acceptance review, the missing artifact is an independently reviewed, canonical-coordinate evidence set that links the registered spatial footprint to an independently established utility lifecycle, plus independently typed predictions evaluated on a held-out cohort. Keep player association separately `UNKNOWN` unless independently evidenced; player/charge fusion is VTA-503, not a prerequisite to falsely infer from roster context. Until that artifact exists, supported smoke acceptance and the existing 2490-second correspondence remain unresolved.
