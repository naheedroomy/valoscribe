import { reserveRunOutput, runAnalysis, runPreflight, type AnalyzeInput } from "@/lib/py-bridge";
import { jsonError, mutationOriginAllowed } from "@/lib/server";
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 3600;

function requestInput(body: unknown): AnalyzeInput | null {
  if (!body || typeof body !== "object") return null;
  const value = body as Record<string, unknown>;
  if (typeof value.vodPath !== "string" || typeof value.mapName !== "string" || typeof value.matchId !== "string" || typeof value.mapId !== "string" ||
    !Number.isSafeInteger(value.fromRound) || !Number.isSafeInteger(value.toRound) || typeof value.team !== "string" || typeof value.profilePath !== "string" ||
    typeof value.manifestPath !== "string" || typeof value.outputDir !== "string" || (value.verifySha !== undefined && typeof value.verifySha !== "boolean")) return null;
  return { vodPath: value.vodPath, mapName: value.mapName, matchId: value.matchId, mapId: value.mapId,
    fromRound: value.fromRound as number, toRound: value.toRound as number, team: value.team,
    profilePath: value.profilePath, manifestPath: value.manifestPath, outputDir: value.outputDir, verifySha: value.verifySha !== false };
}

function sse(event: string, payload: unknown): string { return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`; }

export async function POST(request: NextRequest): Promise<Response> {
  if (!mutationOriginAllowed(request)) return jsonError("This local API accepts mutations only from its same-origin loopback studio.", 403);
  let raw: unknown;
  try { raw = await request.json(); } catch { return jsonError("Request body must be valid JSON."); }
  const input = requestInput(raw);
  if (!input || input.fromRound < 1 || input.toRound < input.fromRound || input.toRound > 99) return jsonError("Invalid run request or round range.");
  try {
    const { plan } = await runPreflight(input);
    await reserveRunOutput(input);
    const encoder = new TextEncoder();
    const abortController = new AbortController();
    let closed = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const send = (event: string, data: unknown) => { if (!closed) controller.enqueue(encoder.encode(sse(event, data))); };
        send("status", { message: "Preflight passed; starting the configured CLI operation.", selectedRounds: plan.selected_rounds.length });
        void runAnalysis(input, (channel, text) => send("log", { channel, text }), true, abortController.signal).then((result) => {
          if (result.code === 0) send("complete", { exitCode: 0, outputDir: input.outputDir, artifact: "execution-plan.json", reconstruction: false, message: "CLI completed. This command writes an execution plan only; it does not reconstruct telemetry." });
          else send("error", { exitCode: result.code, message: result.stderr || result.stdout || "CLI exited unsuccessfully." });
        }).catch((error: unknown) => send("error", { message: error instanceof Error ? error.message : "Job failed." })).finally(() => {
          if (!closed) { closed = true; controller.close(); }
        });
      },
      cancel() { closed = true; abortController.abort(); },
    });
    return new Response(stream, { headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no" } });
  } catch (error) { return jsonError(error instanceof Error ? error.message : "Job validation failed closed.", 400); }
}
