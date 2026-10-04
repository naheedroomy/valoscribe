import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { parse } from "yaml";
import { approvedSourceRoot, exampleRoot, jsonError, repositoryRoot, requestIsLocal } from "@/lib/server";
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
type Example = { path: string; data: unknown };

export async function GET(request: NextRequest): Promise<Response> {
  if (!requestIsLocal(request)) return jsonError("The studio APIs are loopback-only.", 403);
  try {
    const entries = await readdir(exampleRoot, { withFileTypes: true });
    const manifests: Example[] = []; const profiles: Example[] = [];
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
      const file = path.join(exampleRoot, entry.name);
      try {
        const data: unknown = JSON.parse(await readFile(file, "utf8"));
        if (data && typeof data === "object" && "rounds" in data && "source_video_sha256" in data) manifests.push({ path: `configs/examples/${entry.name}`, data });
        else if (data && typeof data === "object" && "minimap_crop" in data && "team_calibrations" in data) profiles.push({ path: `configs/examples/${entry.name}`, data });
      } catch { /* Python preflight validates the chosen local fixture. */ }
    }
    const vods: Array<{ path: string; name: string; size: number }> = [];
    for (const root of [approvedSourceRoot, path.join(repositoryRoot, ".local", "media")]) {
      try {
        for (const entry of await readdir(root, { withFileTypes: true })) {
          if (!entry.isFile() || !/\.(mp4|mov|mkv)$/i.test(entry.name)) continue;
          const fullPath = path.join(root, entry.name);
          vods.push({ path: path.relative(repositoryRoot, fullPath), name: entry.name, size: (await stat(fullPath)).size });
        }
      } catch { /* Source folders are optional on another machine. */ }
    }
    const mapConfig = parse(await readFile(path.join(repositoryRoot, "configs", "maps", "ascent.yaml"), "utf8"));
    return Response.json({ presets: manifests.map((manifest) => ({ ...manifest, profiles })), manifests, profiles, vods, mapConfig });
  } catch (error) { return jsonError(error instanceof Error ? error.message : "Could not list local configuration examples.", 500); }
}
