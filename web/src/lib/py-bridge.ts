import { spawn } from "node:child_process";
import path from "node:path";
import { lstat, mkdir, readdir, realpath, stat } from "node:fs/promises";
import type { VODExecutionPlan } from "./types";
import { approvedSourceRoot, exampleRoot, localRoot, repositoryRoot, runsRoot } from "./server";

export interface AnalyzeInput {
  vodPath: string; mapName: string; matchId: string; mapId: string; fromRound: number; toRound: number;
  team: string; profilePath: string; manifestPath: string; outputDir: string; verifySha: boolean;
}
export interface ProcessResult { stdout: string; stderr: string; code: number }

export function runArgv(command: string, args: string[], cwd = repositoryRoot): Promise<ProcessResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, shell: false, windowsHide: true, env: { ...process.env, PYTHONUNBUFFERED: "1" } });
    let stdout = ""; let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
    child.once("error", reject);
    child.once("close", (code) => resolve({ stdout, stderr, code: code ?? 1 }));
  });
}

function relativeContained(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

async function validateInputPaths(input: AnalyzeInput, reservedOutput = false): Promise<void> {
  const vod = path.resolve(repositoryRoot, input.vodPath);
  const realVod = await realpath(vod);
  const roots = [await realpath(approvedSourceRoot), await realpath(localRoot)];
  if (!roots.some((root) => relativeContained(root, realVod))) throw new Error("VOD must be inside ../VOD or .local");
  if (!(await stat(realVod)).isFile()) throw new Error("VOD must be a regular file");
  for (const relative of [input.profilePath, input.manifestPath]) {
    const file = path.resolve(repositoryRoot, relative);
    const canonical = await realpath(file);
    if (!relativeContained(await realpath(exampleRoot), canonical) || !(await stat(canonical)).isFile()) {
      throw new Error("Profile and manifest must be files inside configs/examples");
    }
  }
  const output = path.resolve(repositoryRoot, input.outputDir);
  if (!relativeContained(runsRoot, output) || path.dirname(output) !== runsRoot || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(path.basename(output))) throw new Error("Output must be a new named direct child path under .local/runs");
  if (await realpath(runsRoot) !== runsRoot) throw new Error("The .local/runs output root must not be a symlink");
  try {
    const info = await lstat(output);
    if (!reservedOutput || info.isSymbolicLink() || !info.isDirectory() || (await readdir(output)).length !== 0) throw new Error("Output directory already exists or is not empty; refusing overwrite");
  } catch (error) {
    if (error instanceof Error && error.message.includes("Output directory")) throw error;
    if ((error as NodeJS.ErrnoException).code !== "ENOENT" || reservedOutput) throw error;
  }
}

function cliArgs(input: AnalyzeInput, preflight: boolean): string[] {
  return ["run", "--extra", "parquet", "python", "-m", "valoscribe", "tactical", "analyze-vod",
    "--vod", path.resolve(repositoryRoot, input.vodPath), "--map", input.mapName,
    "--match", input.matchId, "--map-id", input.mapId, "--from-round", String(input.fromRound),
    "--to-round", String(input.toRound), "--team", input.team,
    "--profile", path.resolve(repositoryRoot, input.profilePath),
    "--round-manifest", path.resolve(repositoryRoot, input.manifestPath),
    "--output", path.resolve(repositoryRoot, input.outputDir), preflight ? "--preflight" : "--no-preflight",
    input.verifySha ? "--verify-sha" : "--no-verify-sha"];
}

export async function runPreflight(input: AnalyzeInput): Promise<{ plan: VODExecutionPlan; asciiSummary: string }> {
  await validateInputPaths(input);
  const result = await runArgv("uv", cliArgs(input, true));
  if (result.code !== 0) throw new Error((result.stderr || result.stdout || "Preflight failed").trim());
  const planStart = result.stdout.indexOf("Execution Plan:");
  const tableStart = result.stdout.indexOf("Round Summary Table:");
  if (planStart < 0 || tableStart < 0) throw new Error("Python preflight did not return the expected execution plan");
  const planText = result.stdout.slice(planStart + "Execution Plan:".length, tableStart).trim();
  let plan: VODExecutionPlan;
  try { plan = JSON.parse(planText) as VODExecutionPlan; }
  catch { throw new Error("Python preflight returned invalid execution-plan JSON"); }
  return { plan, asciiSummary: result.stdout.slice(tableStart + "Round Summary Table:".length).trim() };
}

export async function reserveRunOutput(input: AnalyzeInput): Promise<void> {
  await validateInputPaths(input);
  const output = path.resolve(repositoryRoot, input.outputDir);
  await mkdir(output, { recursive: false });
}

export async function runAnalysis(input: AnalyzeInput, onOutput: (channel: "stdout" | "stderr", text: string) => void, reservedOutput = false, signal?: AbortSignal): Promise<ProcessResult> {
  await validateInputPaths(input, reservedOutput);
  return new Promise((resolve, reject) => {
    const child = spawn("uv", cliArgs(input, false), { cwd: repositoryRoot, shell: false, windowsHide: true, signal, env: { ...process.env, PYTHONUNBUFFERED: "1" } });
    let stdout = ""; let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; onOutput("stdout", chunk); });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; onOutput("stderr", chunk); });
    child.once("error", reject);
    child.once("close", (code) => resolve({ stdout, stderr, code: code ?? 1 }));
  });
}
