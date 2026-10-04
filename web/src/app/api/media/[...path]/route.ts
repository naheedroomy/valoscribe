import { createReadStream } from "node:fs";
import { Readable } from "node:stream";
import { resolveAllowedFile, requestIsLocal } from "@/lib/server";
import type { NextRequest } from "next/server";
import { limitOpenEndedRange, parseRange } from "@/lib/media-range";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type RouteContext = { params: Promise<{ path: string[] }> };

async function respond(request: NextRequest, context: RouteContext, headOnly: boolean): Promise<Response> {
  if (!requestIsLocal(request)) return Response.json({ status: "failed", error: "The studio APIs are loopback-only." }, { status: 403 });
  try {
    const { path: parts } = await context.params;
    const file = await resolveAllowedFile(parts.join("/"));
    const rangeHeader = request.headers.get("range");
    const parsedRange = parseRange(rangeHeader, file.size);
    if (parsedRange === "invalid") return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${file.size}`, "Accept-Ranges": "bytes" } });
    const range = limitOpenEndedRange(parsedRange, rangeHeader);
    const start = range?.start ?? 0; const end = range?.end ?? file.size - 1;
    const headers = new Headers({
      "Accept-Ranges": "bytes", "Content-Length": String(Math.max(0, end - start + 1)),
      "Content-Type": file.path.toLowerCase().endsWith(".mp4") ? "video/mp4" : "image/png",
      "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    });
    if (range) headers.set("Content-Range", `bytes ${start}-${end}/${file.size}`);
    if (headOnly) return new Response(null, { status: range ? 206 : 200, headers });
    const stream = createReadStream(file.path, range ? { start, end } : undefined);
    return new Response(Readable.toWeb(stream) as ReadableStream, { status: range ? 206 : 200, headers });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Media unavailable";
    return Response.json({ status: "failed", error: message }, { status: 404 });
  }
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> { return respond(request, context, false); }
export async function HEAD(request: NextRequest, context: RouteContext): Promise<Response> { return respond(request, context, true); }
