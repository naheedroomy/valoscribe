import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { classifyRunArtifacts, isPlanOnlyRun } from "../lib/run-discovery";

test("discovers the existing web-studio plan artifact as plan-only", async () => {
  const planText = await readFile("../.local/runs/web-studio-job-smoke-20261004/execution-plan.json", "utf8");
  const result = classifyRunArtifacts({ manifestText: null, executionPlanText: planText, configSnapshot: null });
  assert.equal(result?.kind, "plan-only");
  assert.equal(result?.executionPlan?.selected_rounds[0]?.round_id, "map3-round4");
  assert.equal(result?.manifest, undefined);
});

test("invalid or missing plan artifacts are not treated as runs", () => {
  for (const input of [
    { manifestText: null, executionPlanText: null, configSnapshot: null },
    { manifestText: null, executionPlanText: "{not json", configSnapshot: null },
    { manifestText: null, executionPlanText: JSON.stringify({ selected_rounds: [] }), configSnapshot: null },
  ]) assert.equal(classifyRunArtifacts(input), null);
  assert.equal(isPlanOnlyRun({}), false);
});

test("discovers valid config snapshots without claiming telemetry", () => {
  assert.equal(classifyRunArtifacts({ manifestText: null, executionPlanText: "bad", configSnapshot: "run:\n  run_id: local-test\n" })?.kind, "config-only");
  assert.equal(classifyRunArtifacts({ manifestText: null, executionPlanText: null, configSnapshot: "[invalid" }), null);
});

test("valid telemetry manifest takes precedence over a plan artifact", () => {
  const manifest = JSON.stringify({ run_id: "run", round_ids: ["round-1"] });
  const plan = JSON.stringify({ match_id: "match", map_id: "map", map_name: "ascent", source_video_path: "vod.mp4", source_video_sha256: "sha", selected_team_id: "A", opponent_team_id: "B", output_dir: "run", selected_rounds: [{ map_round: 1, round_id: "round-1", source_interval_seconds: [10, 20] }] });
  assert.equal(classifyRunArtifacts({ manifestText: manifest, executionPlanText: plan, configSnapshot: null })?.kind, "telemetry");
});
