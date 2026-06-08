export interface ParitySummary {
  suite: string;
  passed: number;
  total: number;
  failures: string[];
}

export function formatSummary(summary: ParitySummary): string {
  const status = summary.failures.length === 0 ? "PASS" : "FAIL";
  return `${summary.suite} parity: ${status} ${summary.passed}/${summary.total}`;
}
