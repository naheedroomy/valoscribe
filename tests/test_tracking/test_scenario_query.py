import json

from typer.testing import CliRunner

from valoscribe.__main__ import app
from valoscribe.analytics.scenarios import ScenarioSearchRecord, match_scenarios
from valoscribe.types.persistent import ScenarioQuery


def row(**updates):
    data = {"round_id": "r1", "segment_id": "s1", "confidence": 0.9, "evidence_ids": ["e1"]}
    data.update(updates)
    return ScenarioSearchRecord.model_validate(data)


def test_filters_require_known_values_and_apply_all_fields():
    records = [
        row(map_id="ascent", control_zones=["a", "b"], utility_ids=["smoke"], phase="execute"),
        row(round_id="r2", segment_id="s2", map_id=None),
        row(round_id="r3", segment_id="s3", map_id="ascent", confidence=0.6),
    ]
    query = ScenarioQuery(map_ids=["ascent", "haven"], required_control_zones=["a"],
                          required_utility_ids=["smoke"], phases=["execute"], confidence_floor=0.8)
    assert [r.round_id for r in match_scenarios(query, records)] == ["r1"]


def test_time_bounds_and_excluded_zone_filters():
    records = [row(display_clock_s=30, control_zones=["a"]), row(round_id="r2", display_clock_s=10)]
    query = ScenarioQuery(min_display_clock_s=20, max_display_clock_s=40,
                          excluded_control_zones=["b"])
    assert [r.round_id for r in match_scenarios(query, records)] == ["r1"]


def test_cli_json_input_outputs_stable_ids_and_rejects_invalid_query(tmp_path):
    query_path, records_path = tmp_path / "query.json", tmp_path / "records.jsonl"
    query_path.write_text('{"map_ids":["ascent"]}', encoding="utf-8")
    records_path.write_text(json.dumps(row(map_id="ascent").model_dump()) + "\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["scenario", "query", str(query_path), str(records_path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "matches": [{"round_id": "r1", "segment_id": "s1"}],
        "schema_version": "1.0",
    }
    query_path.write_text('{"confidence_floor":2}', encoding="utf-8")
    result = CliRunner().invoke(app, ["scenario", "query", str(query_path), str(records_path)])
    assert result.exit_code == 2
    assert "Invalid scenario query input" in result.stderr
