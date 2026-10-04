import { readFile, readdir } from "node:fs/promises";
import { jsonError, listRunDirectories, safeRunDirectoryChild, safeRunFile, requestIsLocal } from "@/lib/server";
import { classifyRunArtifacts } from "@/lib/run-discovery";
import type { NextRequest } from "next/server";

export const runtime = "nodejs";

export async function GET(request: NextRequest): Promise<Response> {
  if (!requestIsLocal(request)) return jsonError("The studio APIs are loopback-only.", 403);
  try {
    const runs = [];
    for (const runId of await listRunDirectories()) {
      try {
        const [manifestText, planText, config] = await Promise.all([
          safeRunFile(runId, "manifest.json").then((file) => readFile(file, "utf8")).catch(() => null),
          safeRunFile(runId, "execution-plan.json").then((file) => readFile(file, "utf8")).catch(() => null),
          safeRunFile(runId, "config.snapshot.yaml").then((file) => readFile(file, "utf8")).catch(() => null),
        ]);
        const artifacts = classifyRunArtifacts({ manifestText, executionPlanText: planText, configSnapshot: config });
        if (!artifacts) continue;
        const manifest = artifacts.manifest ?? {};
        let aggregate: unknown = null;
        try {
          const aggregateDir = await safeRunDirectoryChild(runId, "aggregate");
          const entries = await readdir(aggregateDir, { withFileTypes: true });
          const latest = entries.filter((entry) => entry.isDirectory() && /^derived-revision-\d+$/.test(entry.name)).sort((a, b) => Number(b.name.slice(17)) - Number(a.name.slice(17)))[0];
          if (latest) aggregate = JSON.parse(await readFile(await safeRunFile(runId, `aggregate/${latest.name}/summary.json`), "utf8"));
        } catch { /* Runs without an aggregate summary remain discoverable. */ }
        const rounds = [];
        const roundIds = artifacts.kind === "plan-only"
          ? artifacts.executionPlan?.selected_rounds.map((round) => round.round_id) ?? []
          : Array.isArray(manifest.round_ids) ? manifest.round_ids.filter((id): id is string => typeof id === "string") : [];
        for (const roundId of artifacts.kind === "telemetry" ? roundIds : []) {
          try {
            await safeRunFile(runId, `rounds/${roundId}/summary.json`);
            rounds.push({ roundId, media: [`${runId}/rounds/${roundId}/canonical_playback.mp4`, `${runId}/rounds/${roundId}/minimap_playback.mp4`] });
          } catch { /* Manifest can reference rounds with partial outputs. */ }
        }
        runs.push({ runId, kind: artifacts.kind, manifest, executionPlan: artifacts.executionPlan ?? null, configSnapshot: config, aggregate, rounds: artifacts.kind === "plan-only" ? roundIds.map((roundId) => ({ roundId, media: [] })) : rounds });
      } catch { /* Skip malformed and non-run directories. */ }
    }
    return Response.json({ runs });
  } catch (error) { return jsonError(error instanceof Error ? error.message : "Could not discover local runs.", 500); }
}
