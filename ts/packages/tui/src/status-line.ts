import type { LinuxAgentUiEvent } from "./event-renderer.js";

export interface StatusLineState {
  model?: string;
  activeTool?: string;
  pendingApprovalRequestId?: string;
  finalAnswer?: boolean;
  error?: string;
}

export function applyStatusEvent(
  state: StatusLineState | undefined,
  event: LinuxAgentUiEvent,
): StatusLineState {
  const next: StatusLineState = { ...(state ?? {}) };
  switch (event.type) {
    case "model_start":
      next.model = event.model;
      delete next.finalAnswer;
      delete next.error;
      return next;
    case "tool_start":
      next.activeTool = event.label ?? event.toolName;
      return next;
    case "tool_end":
      delete next.activeTool;
      return next;
    case "hitl_request":
      next.pendingApprovalRequestId = event.request.requestId;
      return next;
    case "approval_decision":
      if (next.pendingApprovalRequestId === event.requestId) {
        delete next.pendingApprovalRequestId;
      }
      return next;
    case "final_answer":
      next.finalAnswer = true;
      delete next.activeTool;
      delete next.pendingApprovalRequestId;
      return next;
    case "error":
      next.error = event.message;
      delete next.activeTool;
      return next;
    case "task_plan_update":
    case "command_output":
      return next;
  }
}

export function renderStatusLine(state: StatusLineState | undefined): string {
  const parts = ["LinuxAgent TS"];
  if (state?.model !== undefined) parts.push(`model ${state.model}`);
  if (state?.activeTool !== undefined) parts.push(`tool ${state.activeTool}`);
  if (state?.pendingApprovalRequestId !== undefined) {
    parts.push(`awaiting approval ${state.pendingApprovalRequestId}`);
  }
  if (state?.finalAnswer) parts.push("final");
  if (state?.error !== undefined) parts.push(`error ${state.error}`);
  return parts.join(" | ");
}
