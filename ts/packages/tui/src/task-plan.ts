import type { Component } from "@earendil-works/pi-tui";

export type TaskPlanStatus = "pending" | "running" | "completed" | "blocked";

export interface TaskPlanItem {
  id: string;
  title: string;
  status: TaskPlanStatus;
}

export function renderTaskPlan(tasks: readonly TaskPlanItem[]): string[] {
  if (tasks.length === 0) return [];
  return ["Plan", ...tasks.map((task) => `${markerForStatus(task.status)} ${task.title}`)];
}

export class TaskPlanPanel implements Component {
  private tasks: TaskPlanItem[] = [];

  update(tasks: readonly TaskPlanItem[]): void {
    this.tasks = tasks.map((task) => ({ ...task }));
  }

  render(width: number): string[] {
    return renderTaskPlan(this.tasks).map((line) => fitLine(line, width));
  }

  invalidate(): void {}
}

function markerForStatus(status: TaskPlanStatus): string {
  switch (status) {
    case "running":
      return ">";
    case "completed":
      return "x";
    case "blocked":
      return "!";
    case "pending":
      return "-";
  }
}

function fitLine(line: string, width: number): string {
  if (width <= 0) return "";
  return line.length <= width ? line : line.slice(0, width);
}
