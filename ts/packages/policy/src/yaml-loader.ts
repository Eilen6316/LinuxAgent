import { readFile } from "node:fs/promises";
import YAML from "yaml";
import type { PolicyRule } from "./engine.js";

interface RawPolicyRule {
  id: string;
  legacy_rule: string;
  level: "SAFE" | "CONFIRM" | "BLOCK";
  risk_score: number;
  capabilities?: string[];
  never_whitelist?: boolean;
}

export async function loadPolicyRules(path: string): Promise<PolicyRule[]> {
  const parsed = YAML.parse(await readFile(path, "utf8")) as { rules?: RawPolicyRule[] };
  return (parsed.rules ?? []).map((rule) => ({
    id: rule.id,
    legacyRule: rule.legacy_rule,
    level: rule.level,
    riskScore: rule.risk_score,
    capabilities: rule.capabilities ?? [],
    neverWhitelist: rule.never_whitelist ?? false,
  }));
}
