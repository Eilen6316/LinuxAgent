import { readFileSync } from "node:fs";
import { chmod, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type {
  applyFilePatchTransaction as applyFilePatchTransactionFunction,
  executeFilePatchTool as executeFilePatchToolFunction,
  FilePatchTransactionResult,
  SessionPermissions as SessionPermissionsClass,
} from "@linuxagent/agent-runtime";
import type {
  AuditWriter as AuditWriterClass,
  verifyAuditLog as verifyAuditLogFunction,
} from "@linuxagent/audit";
import { redactOutput } from "@linuxagent/executor";
import type { NoopSandboxRunner as NoopSandboxRunnerClass } from "@linuxagent/sandbox";
import type {
  buildOpenSshArgv as buildOpenSshArgvFunction,
  guardRemoteCommand as guardRemoteCommandFunction,
} from "@linuxagent/ssh";
import type { PolicyLevel } from "../../packages/contracts/src/index.js";
import type { PolicyEngine as PolicyEngineClass } from "../../packages/policy/src/index.js";
import { formatSummary, type ParitySummary } from "./report.js";

type PolicySource = "llm" | "operator" | "runbook";

interface PolicyFixtureRecord {
  case_id: string;
  input: {
    argv: string[];
    source: PolicySource;
  };
  expected: {
    level: PolicyLevel;
    neverWhitelist: boolean;
    matchedRules: string[];
    capabilities: string[];
  };
}

export { formatSummary };
export type { ParitySummary };

export async function runPolicyParity(
  fixturePath = defaultPolicyFixturePath(),
): Promise<ParitySummary> {
  const PolicyEngine = await loadPolicyEngine();
  const engine = await PolicyEngine.loadFromYaml(defaultPolicyConfigPath());
  const records = readPolicyFixtureRecords(fixturePath);
  const failures: string[] = [];

  for (const record of records) {
    const actual = engine.evaluate(record.input.argv, { source: record.input.source });
    if (actual.level !== record.expected.level) {
      failures.push(
        `${record.case_id}: expected level ${record.expected.level}, got ${actual.level}`,
      );
    }
    if (actual.neverWhitelist !== record.expected.neverWhitelist) {
      failures.push(
        `${record.case_id}: expected neverWhitelist ${record.expected.neverWhitelist}, got ${actual.neverWhitelist}`,
      );
    }
    if (!sameStringSet(actual.matchedRules, record.expected.matchedRules)) {
      failures.push(
        `${record.case_id}: expected matchedRules ${formatStrings(
          record.expected.matchedRules,
        )}, got ${formatStrings(actual.matchedRules)}`,
      );
    }
    if (!sameStringSet(actual.capabilities, record.expected.capabilities)) {
      failures.push(
        `${record.case_id}: expected capabilities ${formatStrings(
          record.expected.capabilities,
        )}, got ${formatStrings(actual.capabilities)}`,
      );
    }
  }

  return {
    suite: "policy",
    passed: records.length - new Set(failures.map((failure) => failure.split(":")[0])).size,
    total: records.length,
    failures,
  };
}

export async function runParitySuites(
  policyFixturePath = defaultPolicyFixturePath(),
): Promise<ParitySummary[]> {
  return [
    await runPolicyParity(policyFixturePath),
    await runAuditParity(),
    await runSandboxParity(),
    runOutputRedactionParity(),
    await runFilePatchParity(),
    await runHitlParity(),
    await runSshParity(),
    runHarnessParity(),
    await runRedTeamParity(),
  ];
}

export async function runAuditParity(): Promise<ParitySummary> {
  const { AuditWriter, verifyAuditLog } = await loadAuditModule();
  const failures: string[] = [];
  const dir = await mkdtemp(resolve(tmpdir(), "linuxagent-audit-parity-"));
  const validPath = resolve(dir, "valid.log");
  const tamperedPath = resolve(dir, "tampered.log");

  await new AuditWriter(validPath).append("hitl.decision", { decision: "approve" });
  const valid = await verifyAuditLog(validPath);
  if (valid.status !== "valid" || valid.entries.length !== 1) {
    failures.push(`valid log: expected valid/1, got ${valid.status}`);
  }

  await writeFile(tamperedPath, await readFile(validPath, "utf8"), { mode: 0o600 });
  await chmod(tamperedPath, 0o600);
  const tamperedText = await readFile(tamperedPath, "utf8");
  await writeFile(tamperedPath, tamperedText.replace("approve", "deny"), { mode: 0o600 });
  const tampered = await verifyAuditLog(tamperedPath);
  if (tampered.status !== "invalid" || tampered.reason !== "hash mismatch") {
    failures.push(`tampered log: expected invalid/hash mismatch, got ${tampered.status}`);
  }

  return { suite: "audit", passed: 2 - failures.length, total: 2, failures };
}

export async function runSandboxParity(): Promise<ParitySummary> {
  const { NoopSandboxRunner } = await loadSandboxModule();
  const failures: string[] = [];
  const runner = new NoopSandboxRunner();

  if (runner.canEnforce("read_only")) {
    failures.push("noop runner must not enforce read_only");
  }

  const passthrough = await runner.execute(["node", "--version"], {
    profile: "noop",
    timeoutMs: 1000,
  });
  if (
    passthrough.enforced !== false ||
    passthrough.runner !== "noop" ||
    passthrough.exitCode !== 0
  ) {
    failures.push("noop execution must remain auditable passthrough with enforced=false");
  }

  return { suite: "sandbox", passed: 2 - failures.length, total: 2, failures };
}

export function runOutputRedactionParity(): ParitySummary {
  const failures: string[] = [];
  const bearer = redactOutput("Authorization: Bearer runtime-secret-token");
  if (bearer.text.includes("runtime-secret-token") || !bearer.redacted) {
    failures.push("bearer token must be redacted before model-facing analysis");
  }

  const bounded = redactOutput(`token sk-${"a".repeat(32)} ${"x".repeat(20)}`, 20);
  if (bounded.text.includes("sk-") || !bounded.text.includes("[TRUNCATED]") || !bounded.truncated) {
    failures.push("bounded output must redact before truncation");
  }

  return { suite: "output-redaction", passed: 2 - failures.length, total: 2, failures };
}

export async function runFilePatchParity(): Promise<ParitySummary> {
  const { applyFilePatchTransaction, executeFilePatchTool } = await loadFilePatchModule();
  const failures: string[] = [];
  if (!(await filePatchApplyPasses(applyFilePatchTransaction))) {
    failures.push("approved file patch must write the expected content");
  }
  if (!(await filePatchRollbackPasses(applyFilePatchTransaction))) {
    failures.push("failed file patch transaction must roll back earlier writes");
  }
  if (!(await filePatchToolPathPolicyPasses(executeFilePatchTool))) {
    failures.push("file patch tool must fail closed before approval for disallowed paths");
  }
  return { suite: "file-patch", passed: 3 - failures.length, total: 3, failures };
}

export async function runHitlParity(): Promise<ParitySummary> {
  const { SessionPermissions } = await loadHitlModule();
  const failures: string[] = [];
  const permissions = new SessionPermissions();
  permissions.allow({ threadId: "thread-1" }, ["uname", "-a"]);
  if (!permissions.isAllowed({ threadId: "thread-1" }, ["uname", "-a"])) {
    failures.push("same thread permission must allow identical argv");
  }
  if (permissions.isAllowed({ threadId: "thread-2" }, ["uname", "-a"])) {
    failures.push("different thread must not inherit permission");
  }
  if (
    !permissions.isAllowed({ threadId: "resume-thread", resumedFromThreadId: "thread-1" }, [
      "uname",
      "-a",
    ])
  ) {
    failures.push("resumed thread must inherit original thread permission");
  }
  return { suite: "hitl", passed: 3 - failures.length, total: 3, failures };
}

export async function runSshParity(): Promise<ParitySummary> {
  const { buildOpenSshArgv, guardRemoteCommand } = await loadSshModule();
  const failures: string[] = [];
  const argv = buildOpenSshArgv(
    {
      name: "prod-web",
      host: "192.0.2.10",
      port: 22,
      username: "operator",
      keyPath: "/home/operator/.ssh/id_ed25519",
      knownHostsPath: "/home/operator/.ssh/known_hosts",
      allowedWorkdirs: ["/var/log"],
      sudoPolicy: "none",
    },
    "uptime",
  );
  const argvText = argv.join("\0");
  if (
    !argvText.includes("StrictHostKeyChecking=yes") ||
    !argvText.includes("UserKnownHostsFile=/home/operator/.ssh/known_hosts")
  ) {
    failures.push("OpenSSH argv must reject unknown hosts with explicit known_hosts");
  }
  const guarded = guardRemoteCommand("journalctl | tail");
  if (guarded.level !== "CONFIRM") {
    failures.push("remote shell metacharacters must require confirmation");
  }
  return { suite: "ssh", passed: 2 - failures.length, total: 2, failures };
}

export function runHarnessParity(fixturePath = defaultHarnessFixturePath()): ParitySummary {
  const records = readHarnessFixtureRecords(fixturePath);
  const failures: string[] = [];
  const sources = new Set(records.map((record) => record.source));
  for (const source of REQUIRED_HARNESS_SOURCES) {
    if (!sources.has(source)) {
      failures.push(`missing harness scenario: ${source}`);
    }
  }
  for (const record of records) {
    const serialized = JSON.stringify(record);
    if (/\/home\/(?!operator\b)|\/root\/\.ssh|secret|token/i.test(serialized)) {
      failures.push(`${record.scenarioId}: fixture must not contain private paths or secrets`);
    }
  }
  return {
    suite: "harness",
    passed: REQUIRED_HARNESS_SOURCES.length - failures.length,
    total: REQUIRED_HARNESS_SOURCES.length,
    failures,
  };
}

export async function runRedTeamParity(
  fixturePath = defaultRedTeamFixturePath(),
): Promise<ParitySummary> {
  const PolicyEngine = await loadPolicyEngine();
  const engine = await PolicyEngine.loadFromYaml(defaultPolicyConfigPath());
  const records = readRedTeamFixtureRecords(fixturePath);
  const failures: string[] = [];

  for (const record of records) {
    const actual = engine.evaluate(record.input.argv, { source: record.input.source });
    if (!meetsMinimumLevel(actual.level, record.expected.minimumLevel)) {
      failures.push(
        `${record.case_id}: expected at least ${record.expected.minimumLevel}, got ${actual.level}`,
      );
    }
    if (actual.neverWhitelist !== record.expected.neverWhitelist) {
      failures.push(
        `${record.case_id}: expected neverWhitelist ${record.expected.neverWhitelist}, got ${actual.neverWhitelist}`,
      );
    }
    for (const rule of record.expected.requiredMatchedRules) {
      if (!actual.matchedRules.includes(rule)) {
        failures.push(`${record.case_id}: missing matched rule ${rule}`);
      }
    }
    for (const capability of record.expected.requiredCapabilities) {
      if (!actual.capabilities.includes(capability)) {
        failures.push(`${record.case_id}: missing capability ${capability}`);
      }
    }
  }

  return {
    suite: "red-team",
    passed: records.length - new Set(failures.map((failure) => failure.split(":")[0])).size,
    total: records.length,
    failures,
  };
}

export async function main(argv = process.argv.slice(2)): Promise<number> {
  const summaries = await runParitySuites(argv[0] ?? defaultPolicyFixturePath());
  const failures = summaries.flatMap((summary) => summary.failures);

  for (const summary of summaries) {
    console.log(formatSummary(summary));
  }
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }

  return failures.length === 0 ? 0 : 1;
}

function defaultPolicyFixturePath(): string {
  return resolve(process.cwd(), "parity/fixtures/command-policy.jsonl");
}

function defaultHarnessFixturePath(): string {
  return resolve(process.cwd(), "parity/fixtures/harness-scenarios.jsonl");
}

function defaultRedTeamFixturePath(): string {
  return resolve(process.cwd(), "parity/fixtures/red-team-policy.jsonl");
}

function defaultPolicyConfigPath(): string {
  return resolve(process.cwd(), "../configs/policy.default.yaml");
}

function readPolicyFixtureRecords(fixturePath: string): PolicyFixtureRecord[] {
  const content = readFileSync(fixturePath, "utf8").trim();
  if (content.length === 0) return [];
  return content
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as PolicyFixtureRecord);
}

interface HarnessFixtureRecord {
  scenarioId: string;
  source: string;
}

const REQUIRED_HARNESS_SOURCES = [
  "tests/harness/scenarios/parallel_direct_answer_boundary.yaml",
  "tests/harness/scenarios/hitl_llm_first_run.yaml",
  "tests/harness/scenarios/hitl_destructive_never_wl.yaml",
  "tests/harness/scenarios/hitl_non_tty_auto_deny.yaml",
  "tests/harness/scenarios/file_patch_existing_script_tools.yaml",
  "tests/harness/scenarios/sandbox_local_fail_closed.yaml",
  "tests/harness/scenarios/output_redaction_before_analysis.yaml",
  "tests/harness/scenarios/cluster_remote_shell_syntax.yaml",
] as const;

function readHarnessFixtureRecords(fixturePath: string): HarnessFixtureRecord[] {
  const content = readFileSync(fixturePath, "utf8").trim();
  if (content.length === 0) return [];
  return content
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as HarnessFixtureRecord);
}

interface RedTeamFixtureRecord {
  case_id: string;
  input: {
    argv: string[];
    source: PolicySource;
  };
  expected: {
    minimumLevel: PolicyLevel;
    neverWhitelist: boolean;
    requiredMatchedRules: string[];
    requiredCapabilities: string[];
  };
}

function readRedTeamFixtureRecords(fixturePath: string): RedTeamFixtureRecord[] {
  const content = readFileSync(fixturePath, "utf8").trim();
  if (content.length === 0) return [];
  return content
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as RedTeamFixtureRecord);
}

function meetsMinimumLevel(actual: PolicyLevel, expected: PolicyLevel): boolean {
  return POLICY_LEVEL_RANK[actual] >= POLICY_LEVEL_RANK[expected];
}

function sameStringSet(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const expected = new Set(right);
  return left.every((item) => expected.has(item));
}

function formatStrings(items: readonly string[]): string {
  return `[${[...items].sort().join(", ")}]`;
}

const POLICY_LEVEL_RANK: Record<PolicyLevel, number> = {
  SAFE: 0,
  CONFIRM: 1,
  BLOCK: 2,
};

async function loadPolicyEngine(): Promise<typeof PolicyEngineClass> {
  const module = (await import(policyModuleSpecifier())) as {
    PolicyEngine: typeof PolicyEngineClass;
  };
  return module.PolicyEngine;
}

async function loadAuditModule(): Promise<{
  AuditWriter: typeof AuditWriterClass;
  verifyAuditLog: typeof verifyAuditLogFunction;
}> {
  return (await import(auditModuleSpecifier())) as {
    AuditWriter: typeof AuditWriterClass;
    verifyAuditLog: typeof verifyAuditLogFunction;
  };
}

async function loadSandboxModule(): Promise<{
  NoopSandboxRunner: typeof NoopSandboxRunnerClass;
}> {
  return (await import(sandboxModuleSpecifier())) as {
    NoopSandboxRunner: typeof NoopSandboxRunnerClass;
  };
}

async function loadFilePatchModule(): Promise<{
  applyFilePatchTransaction: typeof applyFilePatchTransactionFunction;
  executeFilePatchTool: typeof executeFilePatchToolFunction;
}> {
  return (await import(filePatchModuleSpecifier())) as {
    applyFilePatchTransaction: typeof applyFilePatchTransactionFunction;
    executeFilePatchTool: typeof executeFilePatchToolFunction;
  };
}

async function loadHitlModule(): Promise<{
  SessionPermissions: typeof SessionPermissionsClass;
}> {
  return (await import(hitlModuleSpecifier())) as {
    SessionPermissions: typeof SessionPermissionsClass;
  };
}

async function loadSshModule(): Promise<{
  buildOpenSshArgv: typeof buildOpenSshArgvFunction;
  guardRemoteCommand: typeof guardRemoteCommandFunction;
}> {
  return (await import(sshModuleSpecifier())) as {
    buildOpenSshArgv: typeof buildOpenSshArgvFunction;
    guardRemoteCommand: typeof guardRemoteCommandFunction;
  };
}

function policyModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/policy/src/index.js";
  }
  return "../../packages/policy/dist/src/index.js";
}

function auditModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/audit/src/index.js";
  }
  return "../../packages/audit/dist/src/index.js";
}

function sandboxModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/sandbox/src/index.js";
  }
  return "../../packages/sandbox/dist/src/index.js";
}

function filePatchModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/agent-runtime/src/file-patch/index.js";
  }
  return "../../packages/agent-runtime/dist/src/file-patch/index.js";
}

function hitlModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/agent-runtime/src/index.js";
  }
  return "../../packages/agent-runtime/dist/src/index.js";
}

function sshModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/ssh/src/index.js";
  }
  return "../../packages/ssh/dist/src/index.js";
}

async function filePatchApplyPasses(
  applyFilePatchTransaction: typeof applyFilePatchTransactionFunction,
): Promise<boolean> {
  const dir = await mkdtemp(resolve(tmpdir(), "linuxagent-file-patch-parity-"));
  const target = resolve(dir, "apply.txt");
  await writeFile(target, "old\n", "utf8");
  const result = await applyFilePatchTransaction(
    {
      version: 1,
      requestIntent: "update",
      summary: "apply parity",
      patches: [{ path: target, diff: diffFor(target, "old", "new") }],
    },
    { approvePatch: async () => "approve" },
    new MemoryPatchAudit(),
  );
  return result.applied && !result.rolledBack && (await readFile(target, "utf8")) === "new\n";
}

async function filePatchRollbackPasses(
  applyFilePatchTransaction: typeof applyFilePatchTransactionFunction,
): Promise<boolean> {
  const dir = await mkdtemp(resolve(tmpdir(), "linuxagent-file-patch-parity-"));
  const first = resolve(dir, "first.txt");
  const second = resolve(dir, "second.txt");
  const audit = new MemoryPatchAudit();
  await writeFile(first, "old\n", "utf8");
  await writeFile(second, "stable\n", "utf8");
  try {
    await applyFilePatchTransaction(
      {
        version: 1,
        requestIntent: "update",
        summary: "rollback parity",
        patches: [
          { path: first, diff: diffFor(first, "old", "new") },
          { path: second, diff: diffFor(second, "missing", "changed") },
        ],
      },
      { approvePatch: async () => "approve" },
      audit,
    );
  } catch {
    const result = audit.lastResult();
    return (
      (await readFile(first, "utf8")) === "old\n" &&
      (await readFile(second, "utf8")) === "stable\n" &&
      result?.rolledBack === true
    );
  }
  return false;
}

async function filePatchToolPathPolicyPasses(
  executeFilePatchTool: typeof executeFilePatchToolFunction,
): Promise<boolean> {
  const allowed = await mkdtemp(resolve(tmpdir(), "linuxagent-file-patch-allowed-"));
  const outside = await mkdtemp(resolve(tmpdir(), "linuxagent-file-patch-outside-"));
  const target = resolve(outside, "example.txt");
  await writeFile(target, "old\n", "utf8");
  let approvalCalls = 0;
  const auditEvents: Array<{ eventType: string; payload: Record<string, unknown> }> = [];
  const result = await executeFilePatchTool({
    args: {
      version: 1,
      requestIntent: "update",
      summary: "blocked write",
      patches: [
        {
          path: target,
          diff: diffFor(target, "old", "new"),
        },
      ],
    },
    pathPolicy: { allowedRoots: [allowed] },
    approval: {
      approvePatch: async () => {
        approvalCalls += 1;
        return "approve";
      },
    },
    audit: {
      append: async (eventType, payload) => {
        auditEvents.push({ eventType, payload });
      },
    },
  });

  return (
    result.executed === false &&
    result.blockedReason.includes("path outside allowed roots") &&
    approvalCalls === 0 &&
    (await readFile(target, "utf8")) === "old\n" &&
    auditEvents[0]?.eventType === "file_patch.block"
  );
}

function diffFor(path: string, oldText: string, newText: string): string {
  return `--- ${path}\n+++ ${path}\n@@ -1 +1 @@\n-${oldText}\n+${newText}\n`;
}

class MemoryPatchAudit {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }

  lastResult(): (FilePatchTransactionResult & { success?: boolean }) | undefined {
    return this.events.findLast((event) => event.eventType === "file_patch.result")?.payload as
      | (FilePatchTransactionResult & { success?: boolean })
      | undefined;
  }
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const exitCode = await main();
  process.exitCode = exitCode;
}
