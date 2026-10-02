# VTA-704 implementation plan

## Scope and seam

Build a new round-analysis reporting path above existing deterministic analytics and provider abstractions. Do not redesign VTA-701/702 or CV/tracking. Keep the existing exact-fact `generate_narrative(RoundAggregate, ...)` API intact. New contracts represent an evidence bundle, imported HUD event references including source-reported confidence/EvidenceRef provenance, anonymous diagnostic availability, and classified report content. New CLI command validates local input and writes JSON + Markdown without overwrite. Optional provider consumes only IDs, locally authored fact text, bounded numeric confidence/evidence metadata, and timestamps; arbitrary upstream evidence notes stay local. Source timestamps and clock domains remain distinct.

## Work sequence

1. Add strict typed persistent contracts first: evidence source/reference, upstream event bundle, availability/provenance, analysis result with observations vs hypothetical interpretations/recommendations.
2. Implement bounded JSON/JSONL adapter. Resolve event identity fields from real upstream records without rewriting original payload; require explicit matching IDs, source clock, and a bounds review reference; validate timestamp/bounds while supporting legacy records whose round is identifiable only from the declared reviewed interval. Diagnostic JSON remains metadata only.
3. Derive deterministic facts only for supported upstream event types/fields. Do not derive tactical aggregates from anonymous sample counts. Preserve sample counts by source and missing-evidence state.
4. Implement one optional structured response with selected fact IDs plus bounded hypotheses and coaching recommendations. Response schema fields are all required and every object forbids extra fields. Resolve hypothesis/recommendation citations to source line and source timestamp locally. Render claim text only under explicitly hypothetical/suggested headings; any parse/schema/citation/provider failure discards all model analysis and retains deterministic observations.
5. Add `round-analysis` Typer command, collision-safe paired JSON/Markdown writer, examples and focused tests. Baseline compatibility tests plus focused round-analysis tests; then required full suite, ruff, and mypy.

## Verification matrix

| Criterion | Verification |
|---|---|
| Typed event import | synthetic upstream JSONL fixture preserves arbitrary original fields, IDs, timestamp, clock-domain marker; malformed JSON and invalid schema rejected |
| Correct round scope | match/map/round mismatch and timestamp/bounds violation rejected; no implicit clock conversion |
| Honest diagnostic-only output | anonymous-only fixture yields unavailable tactical facts and diagnostic counts/provenance, not player/side/movement claims or fabricated aggregate |
| Deterministic path | no key/default-off produces JSON+Markdown with explicit missing evidence and stable output |
| Optional provider | fake/injected OpenAI-compatible transport confirms strict nested JSON Schema, selected IDs, tentative hypotheses/recommendations and locally resolved citations without network; arbitrary EvidenceRef notes never reach prompts; unknown/duplicate IDs, unsupported references, refusal/truncation, explicit non-`stop` finish reason, and provider failure discard model analysis; missing legacy finish_reason remains supported |
| Safety/output | prompt-like evidence remains data; no secret in output; existing output collision does not overwrite; partial pair is removed |
| Compatibility | existing narrative/report/provider tests unchanged and pass |

## Initial implementation vs. future roadmap

### Stage 0 — This VTA-704 software slice (implemented here)

- Accept a single synthetic or explicitly reviewed source round; keep unknown data unknown.
- Produce deterministic event observations, optional model-selected facts, cited single-round hypotheses, and suggested coaching practices. The model may not create observation text.
- Keep anonymous diagnostics metadata-only in both JSON and Markdown.
- Verification commands:
  `uv run pytest tests/test_round_analysis.py tests/test_reporting_narrative.py tests/test_reporting.py tests/test_llm_provider.py`
  `uv run python -m valoscribe round-analysis run docs/vta704-example/round-analysis-bundle.json --output-dir "/tmp/vta704-round-analysis-$(date +%s)"`
  `uv run ruff check src tests && uv run mypy src/valoscribe`

### Stage 1 — Accepted real HUD source and evidence audit (future; not accepted by Stage 0)

- Obtain one genuine upstream `event_log.jsonl`, reviewed match/map/round identifiers, source clock-domain declaration, and reviewed round timestamp bounds with provenance.
- Compare every included event and exact JSONL line/timestamp to the reviewed source; record unsupported fields, OCR/detector caveats, and identity validation status. No inference claim until event correctness is independently reviewed.
- Verification: run the `round-analysis` CLI with the reviewed bundle; retain JSON/Markdown artifacts; have an independent analyst reconcile every output fact and citation to its source line. Acceptance remains pending until the real artifact and reconciliation are attached.

### Stage 2 — Deterministic multi-round evidence aggregation (future, before team tendencies)

- Reuse existing scenario/aggregate contracts; do not synthesize player movement or round features from anonymous samples. Require multiple individually accepted round records and report per-round missingness and source provenance.
- Select the minimum useful sample and comparison cohorts with coaches before evaluation; version that protocol rather than inventing thresholds in this issue.
- Verification: run aggregate/scenario unit tests and the existing CLI query path over a reviewed multi-round fixture; independently recalculate counts from source round IDs.

### Stage 3 — Cross-VOD repeatability and anti-strat candidate discovery (future)

- Compare a team's reviewed tendencies across separately sourced VODs and maps/sides; distinguish one-round observations from repeated patterns and disclose distribution/coverage. Do not fix broadcast color to a permanent side.
- Require a held-out VOD evaluation and independent analyst review before labeling a behavior a team habit or anti-strat signal.
- Verification: report source-VOD and unique-round counts for every cohort; rerun aggregation on a held-out fixture and compare with independent calculations. Candidate-discovery output remains a hypothesis until reviewed.

### Stage 4 — Coaching learning loop (future)

- Let coaches accept, reject, or amend hypotheses/recommendations with attributable evidence; retain correction history separately from raw source events and derived model claims.
- Evaluate analyst agreement, citation correctness, false tactical claims, and whether a recommendation was actually useful. Never train or claim quality solely from model self-confidence.
- Verification: replay a versioned coach-reviewed evaluation set; report each metric and reviewer disagreement. No production-quality claim until acceptance thresholds are agreed and met.

Across all stages, synthetic fixtures prove software mechanics only. The available anonymous VTA-404 diagnostic is not tactical evidence and must not be represented as a real HUD round aggregate.