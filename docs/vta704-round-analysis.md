# VTA-704 round analysis CLI

This first slice inventories source HUD event records for one explicitly scoped round. It does not infer tactical patterns from anonymous minimap diagnostics.

Example input fixtures in `docs/vta704-example/` are synthetic and are not evaluation evidence:

```bash
uv run python -m valoscribe round-analysis run \
  docs/vta704-example/round-analysis-bundle.json \
  --output-dir /tmp/vta704-round-analysis-output
```

The command writes `round_analysis.json` and `round_analysis.md`; output files are exclusive-create and existing outputs are never replaced. `event_log_path` in a bundle is relative to that bundle. The event source declares its clock domain and inclusive source-timestamp bounds plus a review reference. Existing full-match JSONL events for other round numbers are ignored after all explicit IDs and clock domains are validated; malformed identifiers, explicit clock mismatch, matching-round bounds violations, and declared scope mismatches fail closed. Exact JSONL line numbers (including skipped rounds and blank lines) are used for evidence IDs.

Optional model selection is explicit (`--enabled`) and also requires `LLM_ENABLED=true` plus configured `LLM_API_KEY`, `LLM_MODEL`, and other existing provider settings. The provider receives only locally generated fact IDs, safe allowlisted event summaries, source timestamps, source-reported numeric confidence/status, and bounded EvidenceRef source/time/confidence metadata—not original event payloads or video. Player names, EvidenceRef notes, and arbitrary event fields are excluded. Upstream confidence and valid EvidenceRefs remain typed JSON metadata and are summarized in Markdown for all event types; values are source-reported and uncalibrated, while missing/unsupported metadata is marked explicitly. The model may select facts and return bounded hypotheses/recommendations citing known fact IDs. Citation line numbers, evidence IDs, source clocks, and timestamps are resolved locally. Refusal, provider failure, invalid schema/citations, unknown IDs, or an explicit non-`stop` `finish_reason` retain deterministic observations and discard all model claims. Legacy provider envelopes with no `finish_reason` remain accepted.

The actual VTA-404 anonymous diagnostic report is snapshotted in `docs/vta704-example/round4-diagnostic-report.json` (local source path redacted) and consumed by `diagnostic-only-bundle.json`. Counts/provenance appear in both output JSON and Markdown; missing HUD facts remain unknown, and no diagnostic metric is promoted to a tactical claim. `docs/vta704-example/fake-provider/round_analysis.json` and `.md` demonstrate an offline injected-provider run over synthetic HUD events; claims are synthetic illustrations, not live analyses or tactical evaluation. No accepted real HUD source artifact was available for tactical acceptance; real-source validation remains pending.