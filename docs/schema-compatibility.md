# Persistent schema compatibility

Persistent tactical-analysis records use versioned Pydantic contracts in
`src/valoscribe/types/persistent.py`. Their field names and serialized meanings
are part of the stored-data interface.

- Readers reject unknown fields. Any field addition, including an optional
  field, is therefore a schema change and requires a new `schema_version` plus
  an explicit reader compatibility path or migration. Never silently add fields
  to an existing version.
- Renaming/removing a field, changing its meaning or type, tightening validation
  so existing records fail, or changing a versioned enum's interpretation is an
  incompatible change. These changes require a new `schema_version` and an
  explicit migration or documented reader compatibility path.
- `PlayerDetection` represents raw per-frame CV candidates. It must remain a
  separate record from `PlayerTrackPoint`, which represents temporally
  associated/derived output. Track corrections must not overwrite detections.
- `UtilityEvent`, `EvidenceRef`, and `PatternSummary` retain their evidence and
  confidence fields; inferences must not be persisted without provenance.
  Evidence attached to a track or utility event must identify the same match,
  map, and round as its parent record.
- Pydantic models are frozen against field reassignment, but nested Python
  containers are not deeply immutable. Their serializers revalidate the model
  before JSON persistence so post-validation mutations cannot bypass model
  invariants. Use the model serializers for persisted output.
- Geometry and aggregate payloads accept only JSON-compatible values. The
  serializer rejects values that become invalid after model construction.
- `RunManifest` is versioned independently by its own `schema_version` contract.
- `SmokeEvaluation` is V2 because median timing metrics were added. Its reader
  explicitly migrates V1 evaluation payloads (which have only mean metrics) to
  V2 with null medians; serialized V2 output includes both median fields. The
  separate `SupportedSmokeEvaluation` report requires the explicit
  `scope: "supported_agents"` and adds normalized supported-agent names plus
  cohort-exclusion counts. The report rejects UNKNOWN and duplicate normalized
  agent names. `ReviewedSmokeLabel` V1 remains unchanged; the supported-only
  `SupportedReviewedSmokeLabel` is V2 because attribution changed from untyped
  text to scoped `EvidenceRef` records. V1 text-only attribution is not migrated:
  its provenance, scope, and confidence cannot be reconstructed. V2 refs require
  match/map/round to match the label, finite positive confidence, and observed
  (not inferred) evidence with a frame path or note. The evaluator revalidates these records
  before scoring to catch mutations of nested lists. Generic labels without that
  metadata remain excluded from supported evaluation.

Use `model_json_schema()` to publish or inspect the JSON Schema for a contract.
Tests validate serialization and schema generation without external services or
production VOD fixtures.
