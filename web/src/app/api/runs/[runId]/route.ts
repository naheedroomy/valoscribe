import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { parse } from "yaml";
import { classifyRunArtifacts } from "@/lib/run-discovery";
import { safeRunDirectory, safeRunDirectoryChild, safeRunFile, jsonError, requestIsLocal, repositoryRoot } from "@/lib/server";
import type { NextRequest } from "next/server";
import type { Observation, CorrectedObservation, EvidenceRecord } from "@/lib/types";

export const runtime = "nodejs";
type RouteContext = { params: Promise<{ runId: string }> };

async function jsonFile(filePath: string): Promise<unknown | null> {
  try { return JSON.parse(await readFile(filePath, "utf8")); } catch { return null; }
}
async function jsonLines<T>(filePath: string): Promise<T[]> {
  try { return (await readFile(filePath, "utf8")).split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line) as T); }
  catch { return []; }
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  if (!requestIsLocal(request)) return jsonError("The studio APIs are loopback-only.", 403);
  try {
    const { runId } = await context.params;
    await safeRunDirectory(runId);
    const [manifestText, planText, configSnapshot] = await Promise.all([
      safeRunFile(runId, "manifest.json").then((file) => readFile(file, "utf8")).catch(() => null),
      safeRunFile(runId, "execution-plan.json").then((file) => readFile(file, "utf8")).catch(() => null),
      safeRunFile(runId, "config.snapshot.yaml").then((file) => readFile(file, "utf8")).catch(() => null),
    ]);
    const artifacts = classifyRunArtifacts({ manifestText, executionPlanText: planText, configSnapshot });
    if (artifacts?.kind === "plan-only") return Response.json({ runId, kind: "plan-only", executionPlan: artifacts.executionPlan, manifest: null, roundData: [], aggregateSummary: null, availableRoundIds: [], telemetryAvailable: false });
    if (artifacts?.kind === "config-only") return Response.json({ runId, kind: "config-only", configSnapshot, manifest: null, roundData: [], aggregateSummary: null, availableRoundIds: [], telemetryAvailable: false });
    const manifest = artifacts?.manifest ?? await jsonFile(await safeRunFile(runId, "manifest.json"));
    if (!manifest || typeof manifest !== "object") return jsonError("Run manifest is missing or invalid.", 404);
    const mapConfig = parse(await readFile(path.join(repositoryRoot, "configs", "maps", "ascent.yaml"), "utf8")) as { canonical_dimensions_px?: unknown };
    const dimensions = mapConfig.canonical_dimensions_px;
    if (!Array.isArray(dimensions) || dimensions.length !== 2 || !dimensions.every((value) => typeof value === "number")) throw new Error("Ascent map dimensions are invalid.");
    const [mapWidth, mapHeight] = dimensions as [number, number];
    const queryRound = request.nextUrl.searchParams.get("round");
    const roundsDirectory = await safeRunDirectoryChild(runId, "rounds").catch(() => null);
    const roundEntries = roundsDirectory ? await readdir(roundsDirectory, { withFileTypes: true }).catch(() => []) : [];
    const availableRounds = roundEntries.filter((entry) => entry.isDirectory() && (!queryRound || entry.name === queryRound)).map((entry) => entry.name);
    const roundData = [];
    for (const roundId of availableRounds) {
      const [raw, corrections, coverage, adjudications, summary, reviewed] = await Promise.all([
        safeRunFile(runId, `rounds/${roundId}/raw_observations.jsonl`).then(jsonLines<Observation>).catch(() => []),
        safeRunFile(runId, `rounds/${roundId}/corrections.jsonl`).then(jsonLines<EvidenceRecord>).catch(() => []),
        safeRunFile(runId, `rounds/${roundId}/sample_coverage.jsonl`).then(jsonLines<EvidenceRecord>).catch(() => []),
        safeRunFile(runId, `rounds/${roundId}/marker_adjudications.jsonl`).then(jsonLines<EvidenceRecord>).catch(() => []),
        safeRunFile(runId, `rounds/${roundId}/summary.json`).then(jsonFile).catch(() => null),
        safeRunFile(runId, `rounds/${roundId}/reviewed_frames.jsonl`).then(jsonLines<EvidenceRecord>).catch(() => []),
      ]);
      const coverageBySample = new Map(coverage.filter((item) => typeof item.sample_index === "number").map((item) => [item.sample_index as number, item]));
      const effective: CorrectedObservation[] = raw.map((observation, ordinal) => ({
        ...observation, observation_id: `${roundId}:${observation.sample_index}:${ordinal}`, source: "raw",
        corrected: false, correction_ids: [],
      }));
      const seenCorrectionIds = new Set<string>();
      for (const correction of corrections) {
        const operation = correction.operation;
        const targetId = correction.target_observation_id;
        const sampleIndex = correction.sample_index;
        const correctionId = correction.correction_id;
        if (correction.run_id !== runId || correction.round_id !== roundId || typeof sampleIndex !== "number" || !Number.isInteger(sampleIndex) || !coverageBySample.has(sampleIndex)) throw new Error("Correction record does not match run, round, or sampled-frame evidence.");
        if (typeof correctionId !== "string" || seenCorrectionIds.has(correctionId)) throw new Error("Correction IDs must be unique and valid.");
        if (effective.some((item) => item.observation_id === correctionId)) throw new Error("Correction ID collides with an existing observation.");
        seenCorrectionIds.add(correctionId);
        if (!["add", "remove", "move"].includes(String(operation))) throw new Error("Correction operation is invalid.");
        if (operation === "remove" || operation === "move") {
          if (typeof targetId !== "string") throw new Error("Remove/move correction is missing its target observation.");
          const targetIndex = effective.findIndex((item) => item.observation_id === targetId && item.sample_index === sampleIndex);
          const target = effective[targetIndex];
          if (!target || typeof correction.original_canonical_x !== "number" || typeof correction.original_canonical_y !== "number" || Math.abs(target.canonical_x - correction.original_canonical_x) > 1e-6 || Math.abs(target.canonical_y - correction.original_canonical_y) > 1e-6) throw new Error("Correction target or original coordinates do not match the replayed evidence.");
          effective.splice(targetIndex, 1);
        }
        if (operation !== "add" && operation !== "move") continue;
        if (typeof correction.corrected_canonical_x !== "number" || !Number.isFinite(correction.corrected_canonical_x) || correction.corrected_canonical_x < 0 || correction.corrected_canonical_x >= mapWidth || typeof correction.corrected_canonical_y !== "number" || !Number.isFinite(correction.corrected_canonical_y) || correction.corrected_canonical_y < 0 || correction.corrected_canonical_y >= mapHeight) throw new Error("Correction coordinates are missing or outside the canonical map.");
        if (typeof correction.confidence !== "number" || !Number.isFinite(correction.confidence) || correction.confidence < 0 || correction.confidence > 1 || typeof correction.reviewer !== "string" || !correction.reviewer.trim()) throw new Error("Correction confidence or reviewer evidence is invalid.");
        const sample = coverageBySample.get(sampleIndex);
        if (!sample || typeof sample.source_timestamp_seconds !== "number") throw new Error("Correction has no sampled-frame timestamp.");
        effective.push({
          run_id: runId, round_id: roundId, sample_index: sampleIndex,
          source_timestamp_seconds: sample.source_timestamp_seconds as number,
          canonical_x: correction.corrected_canonical_x, canonical_y: correction.corrected_canonical_y,
          confidence: correction.confidence,
          quality_flags: ["manual_correction"], observation_id: correctionId, source: "corrected",
          corrected: true, correction_ids: [correctionId],
          evidenceNotes: [String(correction.note ?? ""), String(correction.reviewer ?? "")],
        });
      }
      roundData.push({
        roundId, summary, rawObservationCount: raw.length, rawObservations: raw,
        correctedObservations: effective.sort((a, b) => a.sample_index - b.sample_index || a.canonical_x - b.canonical_x),
        correctionLog: corrections, sampleCoverage: coverage,
        markerAdjudications: adjudications, reviewedFrames: reviewed,
        media: { canonicalPlayback: `${runId}/rounds/${roundId}/canonical_playback.mp4`, minimapPlayback: `${runId}/rounds/${roundId}/minimap_playback.mp4` },
      });
    }
    const revisionsRoot = await safeRunDirectoryChild(runId, "aggregate").catch(() => null);
    const aggregateEntries = revisionsRoot ? await readdir(revisionsRoot, { withFileTypes: true }).catch(() => []) : [];
    const latest = aggregateEntries.filter((entry) => entry.isDirectory() && /^derived-revision-\d+$/.test(entry.name)).sort((a, b) => Number(b.name.slice(17)) - Number(a.name.slice(17)))[0];
    const aggregateSummary = latest ? await safeRunFile(runId, `aggregate/${latest.name}/summary.json`).then(jsonFile).catch(() => null) : null;
    return Response.json({ runId, manifest, configSnapshot, mapConfig, aggregateSummary, roundData, availableRoundIds: availableRounds });
  } catch (error) { return jsonError(error instanceof Error ? error.message : "Could not read run detail.", 404); }
}
