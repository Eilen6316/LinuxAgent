import type { PolicyDecision, PolicyLevel } from "../../contracts/src/index.js";
import { buildEffectiveCommand, type EffectiveCommand } from "./effective-command.js";

const LEVEL_RANK: Record<PolicyLevel, number> = {
  SAFE: 0,
  CONFIRM: 1,
  BLOCK: 2,
};

export interface PolicyEvaluateOptions {
  source: "llm" | "operator" | "runbook";
}

export interface PolicyRule {
  id: string;
  legacyRule: string;
  level: PolicyLevel;
  riskScore: number;
  capabilities: string[];
  neverWhitelist: boolean;
}

interface PartialDecision {
  level: PolicyLevel;
  reason: string | null;
  riskScore: number;
  capabilities: string[];
  matchedRules: string[];
  neverWhitelist: boolean;
}

export class PolicyEngine {
  constructor(rules: PolicyRule[]) {
    void rules;
  }

  static async loadFromYaml(path: string): Promise<PolicyEngine> {
    const { loadPolicyRules } = await import("./yaml-loader.js");
    return new PolicyEngine(await loadPolicyRules(path));
  }

  evaluate(argv: readonly string[], options: PolicyEvaluateOptions): PolicyDecision {
    const command = buildEffectiveCommand(argv);
    const decisions = [
      ...this.evaluateLocalRules(command),
      ...this.evaluateShellAndLolbins(command),
      ...(options.source === "llm" ? [llmFirstRun()] : []),
    ];
    return mergeDecisions(decisions);
  }

  private evaluateLocalRules(command: EffectiveCommand): PartialDecision[] {
    const decisions: PartialDecision[] = [];
    if (isEmbeddedDanger(command)) {
      decisions.push(
        decision("BLOCK", 100, ["shell.injection", "filesystem.delete"], ["EMBEDDED_DANGER"], {
          reason: "embedded danger pattern",
          neverWhitelist: true,
        }),
      );
    }
    if (isRmRoot(command)) {
      decisions.push(
        decision("BLOCK", 100, ["filesystem.delete"], ["ROOT_PATH"], {
          reason: "destructive command targeting root filesystem",
          neverWhitelist: true,
        }),
        decision("CONFIRM", 85, ["filesystem.delete"], ["DESTRUCTIVE"], {
          reason: "destructive filesystem command",
          neverWhitelist: true,
        }),
        decision("CONFIRM", 75, ["filesystem.mutate"], ["DESTRUCTIVE_ARG"], {
          reason: "destructive filesystem argument",
          neverWhitelist: true,
        }),
      );
    }
    if (isMkfsProtectedBlockDevice(command)) {
      decisions.push(
        decision("BLOCK", 100, ["block_device.mutate"], ["BLOCK_DEVICE_MUTATE"], {
          reason: "format command targeting protected block device",
          neverWhitelist: true,
        }),
        decision("BLOCK", 100, ["filesystem.sensitive_read"], ["SENSITIVE_PATH"], {
          reason: "sensitive path access",
        }),
      );
    }
    if (isServiceMutation(command)) {
      decisions.push(
        decision("CONFIRM", 70, ["service.mutate"], ["DESTRUCTIVE"], {
          reason: "service state mutation",
          neverWhitelist: true,
        }),
      );
    }
    return decisions;
  }

  private evaluateShellAndLolbins(command: EffectiveCommand): PartialDecision[] {
    const decisions: PartialDecision[] = [];
    if (
      command.shell.hasPipeline ||
      command.shell.hasCommandSubstitution ||
      command.shell.hasSubshell
    ) {
      decisions.push(
        decision("CONFIRM", 65, ["shell.control"], ["SHELL_CONTROL"], {
          reason: "shell control operator requires review",
        }),
      );
    }
    if (isInteractiveShell(command)) {
      decisions.push(
        decision("CONFIRM", 65, ["terminal.interactive"], ["INTERACTIVE"], {
          reason: "interactive command",
          neverWhitelist: true,
        }),
      );
    }
    if (isShellCommandString(command)) {
      decisions.push(
        decision("CONFIRM", 75, ["interpreter.escape"], ["LOLBIN_SHELL_C"], {
          reason: "shell command string execution",
          neverWhitelist: true,
        }),
      );
    }
    if (isNetworkToShell(command)) {
      decisions.push(
        decision("BLOCK", 100, ["shell.remote_execute"], ["LOLBIN_NETWORK_TO_SHELL"], {
          reason: "network output piped into shell interpreter",
          neverWhitelist: true,
        }),
      );
    }
    return decisions;
  }
}

function isEmbeddedDanger(command: EffectiveCommand): boolean {
  if (isRmRoot(command)) return true;
  if (command.normalizedExecutable.startsWith("mkfs")) return true;
  return command.args.some((arg) => arg.includes("$(") || arg.includes("`"));
}

function isRmRoot(command: EffectiveCommand): boolean {
  return (
    command.normalizedExecutable === "rm" &&
    hasRecursiveForce(command.args) &&
    command.args.some((arg) => arg === "/" || arg === "/*")
  );
}

function hasRecursiveForce(args: readonly string[]): boolean {
  return args.some((arg) => arg === "-rf" || arg === "-fr" || /^-[rRfF]+$/.test(arg));
}

function isMkfsProtectedBlockDevice(command: EffectiveCommand): boolean {
  return (
    command.normalizedExecutable.startsWith("mkfs") &&
    command.args.some((arg) => /^\/dev\/(sd[a-z]|nvme\d+n\d+|vd[a-z]|mapper\/.+|md\d+)/.test(arg))
  );
}

function isServiceMutation(command: EffectiveCommand): boolean {
  return (
    command.normalizedExecutable === "systemctl" &&
    command.args.some((arg) => ["stop", "restart", "reload", "disable", "enable"].includes(arg))
  );
}

function isInteractiveShell(command: EffectiveCommand): boolean {
  return ["sh", "bash", "dash", "zsh", "fish"].includes(command.normalizedExecutable);
}

function isShellCommandString(command: EffectiveCommand): boolean {
  return isInteractiveShell(command) && command.args.includes("-c");
}

function isNetworkToShell(command: EffectiveCommand): boolean {
  if (!command.shell.invokesShell || !command.shell.hasPipeline) return false;
  return /\b(curl|wget)\b.*\|\s*(sh|bash|dash|zsh|fish)\b/.test(command.shell.rawScript);
}

function llmFirstRun(): PartialDecision {
  return decision("CONFIRM", 30, ["llm.generated"], ["LLM_FIRST_RUN"], {
    reason: "LLM-generated command; first run requires approval",
  });
}

function decision(
  level: PolicyLevel,
  riskScore: number,
  capabilities: string[],
  matchedRules: string[],
  options: {
    reason: string;
    neverWhitelist?: boolean;
  },
): PartialDecision {
  return {
    level,
    reason: options.reason,
    riskScore,
    capabilities,
    matchedRules,
    neverWhitelist: options.neverWhitelist ?? false,
  };
}

function safe(): PolicyDecision {
  return {
    level: "SAFE",
    reason: null,
    riskScore: 0,
    capabilities: [],
    matchedRules: [],
    neverWhitelist: false,
  };
}

function mergeDecisions(decisions: PartialDecision[]): PolicyDecision {
  if (decisions.length === 0) return safe();
  const maxLevel = decisions.reduce(
    (current, candidate) =>
      levelRank(candidate.level) > levelRank(current) ? candidate.level : current,
    "SAFE" as PolicyLevel,
  );
  const ordered = [...decisions].sort((left, right) => {
    const levelDiff = levelRank(right.level) - levelRank(left.level);
    if (levelDiff !== 0) return levelDiff;
    return right.riskScore - left.riskScore;
  });
  return {
    level: maxLevel,
    reason: unique(ordered.map((item) => item.reason).filter((item) => item !== null)).join("; "),
    riskScore: Math.max(...ordered.map((item) => item.riskScore)),
    capabilities: unique(ordered.flatMap((item) => item.capabilities)),
    matchedRules: unique(ordered.flatMap((item) => item.matchedRules)),
    neverWhitelist: ordered.some((item) => item.neverWhitelist),
  };
}

function levelRank(level: PolicyLevel): number {
  return LEVEL_RANK[level];
}

function unique<T>(items: readonly T[]): T[] {
  return [...new Set(items)];
}
