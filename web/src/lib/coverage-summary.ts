export function summarizeCoverage(samples: readonly { coverage_status: string }[] | undefined): string {
  if (!samples?.length) return "Loading stored coverage";
  const counts = new Map<string, number>();
  for (const sample of samples) counts.set(sample.coverage_status, (counts.get(sample.coverage_status) ?? 0) + 1);
  return [...counts].map(([status, count]) => `${status} ${count}`).join(" · ");
}
