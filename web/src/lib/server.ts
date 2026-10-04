import { constants } from "node:fs";
import { access, realpath, stat, readdir } from "node:fs/promises";
import path from "node:path";
import type { NextRequest } from "next/server";

export const repositoryRoot = path.resolve(process.cwd(), "..");
export const localRoot = path.join(repositoryRoot, ".local");
export const runsRoot = path.join(localRoot, "runs");
export const exampleRoot = path.join(repositoryRoot, "configs", "examples");
export const approvedSourceRoot = path.resolve(repositoryRoot, "..", "VOD");

export function jsonError(error: string, status = 400): Response {
  return Response.json({ status: "failed", error }, { status });
}

export function isLoopbackHost(header: string | null): boolean {
  if (!header) return false;
  const host = header.toLowerCase();
  return /^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host);
}

export function requestIsLocal(request: NextRequest): boolean {
  return isLoopbackHost(request.headers.get("host"));
}

export function mutationOriginAllowed(request: NextRequest): boolean {
  if (!requestIsLocal(request)) return false;
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const originUrl = new URL(origin);
    const host = request.headers.get("host");
    return !!host && originUrl.host.toLowerCase() === host.toLowerCase() && ["http:", "https:"].includes(originUrl.protocol);
  } catch { return false; }
}

function isContained(root: string, candidate: string): boolean {
  const rel = path.relative(root, candidate);
  return rel === "" || (!rel.startsWith(`..${path.sep}`) && rel !== ".." && !path.isAbsolute(rel));
}

export async function existingFile(filePath: string): Promise<string> {
  const canonical = await realpath(filePath);
  const info = await stat(canonical);
  if (!info.isFile()) throw new Error("Expected a regular file");
  return canonical;
}

export async function resolveAllowedFile(relativeInput: string): Promise<{ path: string; size: number }> {
  if (!relativeInput || relativeInput.includes("\\") || relativeInput.includes("\0")) throw new Error("Invalid media path");
  const decoded = decodeURIComponent(relativeInput);
  const normalized = decoded.replace(/^\/+/, "");
  if (normalized.split("/").some((part) => part === ".." || part === "." || !part)) throw new Error("Invalid media path");
  const roots = [runsRoot, approvedSourceRoot];
  const candidates = roots.map((root) => path.resolve(root, normalized));
  for (let index = 0; index < candidates.length; index += 1) {
    const candidate = candidates[index];
    if (!isContained(roots[index], candidate)) continue;
    try {
      const canonicalRoot = await realpath(roots[index]);
      const canonical = await realpath(candidate);
      if (!isContained(canonicalRoot, canonical)) continue;
      const info = await stat(canonical);
      if (!info.isFile()) continue;
      if (!/\.(mp4|png)$/i.test(canonical)) throw new Error("Only MP4 and PNG media are available");
      return { path: canonical, size: info.size };
    } catch (error) {
      if (error instanceof Error && error.message === "Only MP4 and PNG media are available") throw error;
    }
  }
  throw new Error("Media file not found in an approved media root");
}

export async function safeRunDirectory(runId: string): Promise<string> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(runId) || runId === "." || runId === "..") throw new Error("Invalid run ID");
  const root = await realpath(runsRoot);
  const candidate = await realpath(path.join(root, runId));
  if (!isContained(root, candidate)) throw new Error("Run path escapes the runs directory");
  const info = await stat(candidate);
  if (!info.isDirectory()) throw new Error("Run is not a directory");
  return candidate;
}

export async function safeRunDirectoryChild(runId: string, relativeDirectory: string): Promise<string> {
  const root = await safeRunDirectory(runId);
  if (!relativeDirectory || relativeDirectory.includes("\\\\") || relativeDirectory.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("Invalid run directory path");
  const directory = await realpath(path.resolve(root, relativeDirectory));
  if (!isContained(root, directory) || !(await stat(directory)).isDirectory()) throw new Error("Run directory is not contained in the run");
  return directory;
}

export async function safeRunFile(runId: string, relativeFile: string): Promise<string> {
  const root = await safeRunDirectory(runId);
  if (!relativeFile || relativeFile.includes("\\\\") || relativeFile.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("Invalid run artifact path");
  const file = path.resolve(root, relativeFile);
  if (!isContained(root, file)) throw new Error("Run artifact escapes the run directory");
  const canonical = await realpath(file);
  if (!isContained(root, canonical) || !(await stat(canonical)).isFile()) throw new Error("Run artifact is not a contained file");
  return canonical;
}

export async function listRunDirectories(): Promise<string[]> {
  await access(runsRoot, constants.R_OK);
  const entries = await readdir(runsRoot, { withFileTypes: true });
  return entries.filter((entry) => entry.isDirectory() && /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(entry.name)).map((entry) => entry.name).sort();
}
