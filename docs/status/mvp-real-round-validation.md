# Real Ascent round validation (partial source-backed observer review)

This report records a bounded source-backed review of the current fork. It is not a human/user acceptance or calibration certificate. Final continuity review is complete with **PARTIAL** assessments only; no round receives PASS or complete-team certification. No detector or full-VOD rerun was performed for this report.

## Source and provenance

- Source: `YTDown.com_YouTube_Media_4LEGEQ8KBS0_100T-vs-LOUD-VCT-Americas-Stage-2-Playoffs-Grand-Final-Map-3-Ascent_001_1080p.mp4`; SHA-256 `a2feb25b842b6c1c2baa17f8ef0c5ecfe1816bd058a1c256350fa95900454c44` (1920×1080).
- Team/side: 100 Thieves (100T), attack, source-specific first-half scoreboard/map review. Do not infer side from broadcast color.
- Evidence run (ignored local data): `.local/runs/ascent-team-movement-mvp005-continuation-r1/`; logical parent run `ascent-team-movement-mvp002-r3`.
- The fork manifest documents raw observations and correction/adjudication histories copied byte-identically from parent, detector not rerun, and the explicit continuation-zone addition used only for commitment guard. Parent manifest SHA-256 `aaaa40ae98e3abd3c2542746af33406bc94516f78a1767d7a65a1d71be729343`; parent configuration `af5b286a7d254da8b1ce33003c1a2a7627b0752e5c8a25dd95da19113b5a25fb`; fork snapshot `19c75996f5b2d29f8f6992c19ea77d8dcf8212aea5bc8cdf1346a52225b53be6`; frozen map `9dc6378c512bcac7fd8596a76860483feb0a7431bec5df8cce3b0874b1317b90`. See `fork-manifest.json`, `parent-manifest.json`, and `continuation-rebuild-audit.json` in that run.
- Parent evidence and config histories remain preserved. Continuation was a user-authorized, bounded amendment; it did not rewrite raw detections or zone polygons/thresholds.

## Selected windows and counts

Five attack rounds were chosen because source broadcast shows the live timer start and usable minimap evidence; each is a partial configured interval, not a complete-round claim. Start/end values are source seconds. R9's replay gap is explicitly excluded.

| Round | Exact configured interval; selection basis | Raw candidates | Corrections | Adjudications | Derived observations (eligible) | Raw sample unknown / excluded | Derived sample unknown / excluded | Opening evidence (usable/32; modal tuple and votes) | Status |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| R4 (`map3-round4`) | 263–330; 263 is first live timer 1:39 after freeze countdown at 262 | 1,625 | 562 | 655 | 1,675 (287) | 0 / 0 | 188 / 0 | 32/32; 1/0/2 (19 votes) | PARTIAL |
| R5 (`map3-round5`) | 379–420; first live timer 1:40, preceding 378 is pre-round 0:00 | 742 | 262 | 310 | 862 (186) | 0 / 0 | 100 / 0 | 32/32; 0/0/2 (24 votes) | PARTIAL |
| R6 (`map3-round6`) | 540–600; first live timer 1:39, preceding 539 is pre-round 0:00 | 1,201 | 842 | 945 | 1,397 (437) | 5 / 0 | 128 / 0 | 32/32; 1/0/1 (13 votes) | PARTIAL |
| R7 (`map3-round7`) | 790–870; first live timer 1:39, preceding 789 is pre-round 0:00 | 1,347 | 197 | 488 | 1,446 (148) | 3 / 0 | 275 / 0 | 32/32; 1/0/1 (21 votes) | PARTIAL |
| R9 (`map3-round9`) | 971–1020; 971–975 replay/transition excluded; first live timer 1:39 at 975 | 581 | 271 | 291 | 740 (215) | 2 / 16 | 104 / 16 | 24/32; 2/0/1 (8 votes), eight opening samples unknown | PARTIAL |

Counts cover configured sample rows; raw and derived unknowns are distinct, and exclusions are not unknown evidence. Raw candidate counts describe detector output, not accepted detections. Derived observation counts are materialized raw plus corrected rows in `derived/revision-001/corrected_observations.jsonl`; eligible is the tactical-eligible subset, not unique players. Correction record counts are append-only deltas, not a count of unique markers. Adjudications are source-backed marker decisions; they do not mark whole frames reviewed. Opening votes are observed-marker modal samples, not full-roster distributions. Supporting per-round records are under `rounds/<round-id>/raw_observations.jsonl`, `corrections.jsonl`, `marker_adjudications.jsonl`, `sample_coverage.jsonl`, and `derived/revision-001/`.

Correction actions were source-anchored manual center support, defer/exclude, and adjudication of sampled candidate markers; raw observations remained unchanged. Historical human labor time was not recorded: **correction effort in human-hours unavailable; not estimated**.

## Review evidence and findings

All five round summaries/playback outputs were checked against source-backed opening evidence, including every recovered 15 continuity sheets and four R9 sequence sheets. Final visual review supports five useful PARTIAL openings and three cautious apparent concentrations (B/A/A) across the complete sampled persistence/guard windows, with no material source question for the user. Crop/transform plausibility and marker overlap remain approximate; overlap, spike occlusion, crop noise, zone-edge and floorplan-mask ambiguity are known misses/false-positive risks. All rounds are **PARTIAL**, not PASS: source-supported centers permit cautious opening summaries, but there is no full-frame approval, no complete-roster count, and boundary perturbation can change exact per-frame zone assignments and candidate timing.

- Opening sheets: `.local/runs/ascent-team-movement-mvp005-continuation-r1/task86-visual-review/map3-round{4,5,6,7,9}-interval-opening-four-paired.png`.
- Commitment/unknown sheets: same folder `map3-round{6,7,9}-commitment-guard-unknown-four-paired.png`.
- Continuity sheets / manifest: `.local/runs/ascent-team-movement-mvp005-continuation-r1/task86-continuity-review/`; manifest confirms 15 sheets and valid hashes. The recovered artifact manifest's pending status was superseded by the completed final bounded review.
- Reusable reviews are copied to `.local/runs/ascent-team-movement-mvp005-continuation-r1/task87-review/`: `task86-real-commitment-evidence-review.md` (source/timing/eligibility), `task86-backsite-continuation-review.md` (rule-scope), and `task86-final-continuity-visual-review.md` (all 15 continuity sheets plus four R9 sequence sheets). These are agent reviews, not user approval.
- Per-round playable evidence: `rounds/<round-id>/derived/revision-001/corrected_minimap.mp4` and `corrected_canonical.mp4`; reports and occupancy at the same revision. See also `aggregate/derived-revision-001/summary.md`, `pattern_table.csv`, and `representative_rounds.json`.

### Supported pattern and event statements

Opening modal tuples by round: R4 1/0/2; R5 0/0/2; R6 1/0/1; R7 1/0/1; R9 2/0/1. The same observed 1/0/1 tuple occurs in R6 and R7: **2/5 selected rounds**, partial-observation denominator. This is a recurring observed pattern candidate, not an asserted tactical tendency or full-team shape.

Three partial-coverage apparent commitment candidates: R6 B, persistence 585.25–587.25 s, reported persistence endpoint 587.25 s; R7 A, persistence 863.00–865.00 s, endpoint 865.00 s; R9 A, persistence 1006.75–1008.75 s, endpoint 1008.75 s. Each has a one-second confirmation guard. Endpoints are not event starts. Exact times/counts are sensitive to approximate marker-center placement and should remain tentative; broad site concentration is plausible. R4/R5 have no supported commitment in this evidence, not proof none occurred.

Every selected round's opposite-side presence remains **unknown**. Raw detector-unknown and corrected derived-partial are distinct: only source-supported eligible centers contribute; raw candidates not explicitly eligible do not. No opposite-side observation was accepted as absence; unknown is not absence.

## Performance and artifacts

The recorded correction-only rebuild was `time uv run valoscribe tactical rebuild --run-dir .local/runs/ascent-team-movement-mvp005-continuation-r1`, wall time **102.76 s**, CPU user 669.036 s, system 22.597 s. The original rebuild audit records **66,805,488 bytes (63.71 MiB)** for the run after its derived output generation; this is the historical rebuild artifact size. The current fork run directory, including later review packets and reports, measures **97,700 KiB (95.41 MiB)**; the difference is accumulated artifacts, not a new rebuild result. Peak RSS was not measured (`reported_peak_rss_bytes: null`), so memory is **unavailable**. The 4 FPS inherited source config was limited to these five configured intervals; this was correction/report regeneration, not detection or full-VOD processing. No source video is stored in the run. Playbacks are encoded MP4 files; no playback frame-sequence output is the product artifact.

## Reset milestone acceptance matrix (spec §19)

| Criterion | Evidence / status |
|---|---|
| 19.1 Repository: preserved work, organized root, one active spec, archive, ignored `.local/`, indexed docs, scope instructions | Inventory/cleanup reports, `specs/active/`, `docs/README.md`, `.gitignore`, `AGENTS.md`; prior reports document RST gates. This documentation update adds current validation. |
| 19.1 Root README verified workflow; clean final git status | **PASS:** README documents the editable local source/config path and links actual execution records: fresh inspect output, analyze run log (35.212123 s, 1,188 samples), and correction-only rebuild audit (102.76 s). After the two authorized logical commits, `git status --short` was empty. |
| 19.1 No secrets; imports/tests work; upstream attribution/license | Final checks: 1,254 passed/1 skipped in 140.99 s, Ruff PASS, mypy PASS (134 files), diff check PASS; bounded scan found zero common secret-signature hits across 531 tracked text files. Offline import and CLI-help checks are recorded in the final handoff. This is a bounded scan, not universal secret certification. MIT license retained. |
| 19.2 One real Ascent VOD/layout; selected team/side; at least five intervals | Source/config hashes and five round records above: evidence present, partial. |
| 19.2 Each round crop/canonical playback, raw observations and correction support, occupancy, opening summary | MP4, JSON/Markdown, CSV/Parquet and raw/correction paths above: present for five rounds. |
| 19.2 Three apparent shifts/regroups/commitments; aggregate pattern with round/time anchors | Three partial apparent commitment candidates and recurring R6/R7 opening tuple above: evidence present, approximate/tentative. |
| 19.2 Unknown/low coverage visible; correction/rebuild without detection | Unknown/partial values in occupancy, summaries and playback; append-only correction/adjudication files and rebuild audit state detector was not invoked: demonstrated. |
| 19.3 Scoped usability for observed evidence | **PASS within partial-observation scope:** the playback/reports answer opening shape for all five selected windows; shift and regroup direction are explicitly unknown in every round; apparent concentration is supported tentatively for R6/R7/R9 and unsupported for R4/R5; opposite-side presence is explicitly unknown for all five. All five remain PARTIAL, and these answers do not certify complete-team strategy, user acceptance, or full-video review. |

## Limitations and next evidence

This is a single source, one broadcast layout, five manually selected windows. Approximate calibration and manual centers limit zone-level precision. No player identity, exact roster, intent, or proof of absence is claimed; no user/human approval or official geometry claim is made. Exact commitment qualifications are sensitivity-prone. No peak-memory measure exists. The final bounded observer review is complete and copied durably, but it covers sampled sheets rather than full-video playback. Preserve partial wording, approximate geometry, tentative endpoint timing, and unknown opposite-side presence; no user question remains on these reviewed samples. Human/user approval, full-team claims, quantitative calibration certification, and full-video review are not established and are not required for the bounded partial-evidence usability acceptance.
