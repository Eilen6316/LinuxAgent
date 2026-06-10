import type { Component } from "@earendil-works/pi-tui";
import type { ApprovalDecision } from "@linuxagent/agent-runtime";
import type { PolicyDecision } from "@linuxagent/contracts";
import { renderHitlOverlay } from "./hitl-overlay.js";
import { applyStatusEvent, renderStatusLine, type StatusLineState } from "./status-line.js";
import { renderTaskPlan, type TaskPlanItem } from "./task-plan.js";

export type LinuxAgentUiEvent =
  | { type: "model_start"; model: string }
  | { type: "tool_start"; toolName: string; label?: string; argv?: readonly string[] }
  | { type: "tool_end"; toolName: string; ok: boolean; exitCode?: number | null }
  | { type: "task_plan_update"; tasks: readonly TaskPlanItem[] }
  | { type: "hitl_request"; request: HitlRequest }
  | { type: "approval_decision"; requestId: string; decision: ApprovalDecision }
  | {
      type: "command_output";
      argv: readonly string[];
      exitCode: number | null;
      stdout?: string;
      stderr?: string;
    }
  | { type: "final_answer"; text: string }
  | { type: "error"; message: string };

export interface HitlRequest {
  requestId: string;
  argv: readonly string[];
  goal: string;
  purpose: string;
  policy: PolicyDecision;
  sandbox: HitlSandbox;
  remote?: HitlRemote;
}

export interface HitlSandbox {
  profile: string;
  runner: string;
  enforced: boolean;
}

export interface HitlRemote {
  type: "ssh";
  host: string;
  profileName: string;
  username?: string;
  port?: number;
  knownHostsPath?: string;
  allowedWorkdirs?: readonly string[];
  sudoPolicy?: string;
}

export class LinuxAgentEventRenderer implements Component {
  private status: StatusLineState | undefined;
  private tasks: TaskPlanItem[] = [];
  private activity: string[] = [];
  private pendingApprovals = new Map<string, HitlRequest>();
  private finalAnswer: string | undefined;
  private error: string | undefined;

  apply(event: LinuxAgentUiEvent): void {
    this.status = applyStatusEvent(this.status, event);
    switch (event.type) {
      case "task_plan_update":
        this.tasks = event.tasks.map((task) => ({ ...task }));
        break;
      case "tool_start":
        this.activity.push(activityForToolStart(event));
        break;
      case "tool_end":
        this.activity.push(
          `${event.toolName}: ${event.ok ? "ok" : "blocked"}${event.exitCode === undefined ? "" : ` exit=${event.exitCode}`}`,
        );
        break;
      case "hitl_request":
        this.pendingApprovals.set(event.request.requestId, event.request);
        break;
      case "approval_decision":
        this.pendingApprovals.delete(event.requestId);
        this.activity.push(`approval ${event.requestId}: ${event.decision}`);
        break;
      case "command_output":
        this.activity.push(`command ${event.argv.join(" ")} exit=${event.exitCode}`);
        break;
      case "final_answer":
        this.finalAnswer = event.text;
        break;
      case "error":
        this.error = event.message;
        break;
      case "model_start":
        break;
    }
  }

  render(width: number): string[] {
    const lines = [renderStatusLine(this.status)];
    if (this.tasks.length > 0) {
      lines.push("", ...renderTaskPlan(this.tasks));
    }
    if (this.activity.length > 0) {
      lines.push("", "Activity", ...this.activity.slice(-5));
    }
    for (const request of this.pendingApprovals.values()) {
      lines.push("", ...renderHitlOverlay(request));
    }
    if (this.finalAnswer !== undefined) {
      lines.push("", "Answer", this.finalAnswer);
    }
    if (this.error !== undefined) {
      lines.push("", "Error", this.error);
    }
    return lines.map((line) => fitLine(line, width));
  }

  invalidate(): void {}
}

function activityForToolStart(event: Extract<LinuxAgentUiEvent, { type: "tool_start" }>): string {
  const label = event.label ?? event.toolName;
  const argv = event.argv === undefined ? "" : ` ${event.argv.join(" ")}`;
  return `${label}${argv}`;
}

function fitLine(line: string, width: number): string {
  if (width <= 0) return "";
  return line.length <= width ? line : line.slice(0, width);
}
