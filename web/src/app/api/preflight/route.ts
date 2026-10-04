import { runPreflight, type AnalyzeInput } from "@/lib/py-bridge";
import { jsonError, mutationOriginAllowed } from "@/lib/server";
import type { NextRequest } from "next/server";

export const runtime = "nodejs";

function validRequest(body: unknown): body is AnalyzeInput {
  if (!body || typeof body !== "object") return false;
  const value = body as Record<string, unknown>;
  return typeof value.vodPath === "string" && typeof value.mapName === "string" && typeof value.matchId === "string" &&
    typeof value.mapId === "string" && Number.isSafeInteger(value.fromRound) && Number.isSafeInteger(value.toRound) &&
    typeof value.team === "string" && typeof value.profilePath === "string" && typeof value.manifestPath === "string" &&
    typeof value.outputDir === "string" && (value.verifySha === undefined || typeof value.verifySha === "boolean") &&
    [value.vodPath, value.mapName, value.matchId, value.mapId, value.team, value.profilePath, value.manifestPath, value.outputDir].every((v) => (v as string).length > 0 && (v as string).length < 2048);
}

export async function POST(request: NextRequest): Promise<Response> {
  if (!mutationOriginAllowed(request)) return jsonError("This local API accepts mutations only from its same-origin loopback studio.", 403);
  let body: unknown;
  try { body = await request.json(); } catch { return jsonError("Request body must be valid JSON."); }
  if (!validRequest(body) || body.fromRound < 1 || body.toRound < body.fromRound || body.toRound > 99) return jsonError("Invalid preflight request fields or round range.");
  try {
    const result = await runPreflight({ ...body, verifySha: body.verifySha ?? true });
    return Response.json({ status: "passed", executionPlan: result.plan, asciiSummary: result.asciiSummary });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "Preflight failed closed.", 400);
  }
}
