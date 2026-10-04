import assert from "node:assert/strict";
import { test } from "node:test";
import { summarizeCoverage } from "../lib/coverage-summary";

test("summarizes actual per-sample coverage records", () => {
  const samples = [
    ...Array.from({ length: 235 }, () => ({ coverage_status: "partial" })),
    ...Array.from({ length: 5 }, () => ({ coverage_status: "unknown" })),
  ];
  assert.equal(summarizeCoverage(samples), "partial 235 · unknown 5");
});

test("keeps missing sample evidence visibly pending", () => {
  assert.equal(summarizeCoverage(undefined), "Loading stored coverage");
  assert.equal(summarizeCoverage([]), "Loading stored coverage");
});
