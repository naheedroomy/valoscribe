import { parse } from "yaml";
import type { PlanOnlyRun, RunKind } from "./types";

export interface DiscoveredRunArtifact {
  kind: RunKind;
  manifest?: Record<string, unknown>;
  executionPlan?: PlanOnlyRun;
  configSnapshot: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isPlanOnlyRun(value: unknown): value is PlanOnlyRun {
  if (!isRecord(value)) return false;
  return typeof value.match_id === "string" && typeof value.map_id === "string" &&
    typeof value.map_name === "string" && typeof value.source_video_path === "string" &&
    typeof value.source_video_sha256 === "string" && typeof value.selected_team_id === "string" &&
    typeof value.opponent_team_id === "string" && typeof value.output_dir === "string" &&
    Array.isArray(value.selected_rounds) && value.selected_rounds.length > 0 &&
    value.selected_rounds.every((round) => isRecord(round) && typeof round.round_id === "string" &&
      typeof round.map_round === "number" && Array.isArray(round.source_interval_seconds) &&
      round.source_interval_seconds.length === 2 && round.source_interval_seconds.every((n) => typeof n === "number"));
}

export function classifyRunArtifacts(artifacts: {
  manifestText: string | null;
  executionPlanText: string | null;
  configSnapshot: string | null;
}): DiscoveredRunArtifact | null {
  if (artifacts.manifestText !== null) {
    try {
      const manifest: unknown = JSON.parse(artifacts.manifestText);
      if (isRecord(manifest) && Array.isArray(manifest.round_ids)) {
        return { kind: "telemetry", manifest, configSnapshot: artifacts.configSnapshot };
      }
    } catch { /* An invalid manifest does not prevent checking independent valid plan artifacts. */ }
  }
  if (artifacts.executionPlanText !== null) {
    try {
      const executionPlan: unknown = JSON.parse(artifacts.executionPlanText);
      if (isPlanOnlyRun(executionPlan)) return { kind: "plan-only", executionPlan, configSnapshot: artifacts.configSnapshot };
    } catch { /* Malformed plans are not discoverable. */ }
  }
  if (artifacts.configSnapshot !== null) {
    try {
      if (isRecord(parse(artifacts.configSnapshot))) return { kind: "config-only", configSnapshot: artifacts.configSnapshot };
    } catch { /* Invalid snapshots are not discoverable artifacts. */ }
  }
  return null;
}
