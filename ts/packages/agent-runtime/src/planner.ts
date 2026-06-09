import { type CommandPlan, CommandPlanSchema } from "@linuxagent/contracts";
import { Value } from "typebox/value";

export type PlannerResult =
  | { ok: true; plan: CommandPlan }
  | {
      ok: false;
      error: "invalid_json" | "schema_invalid";
      detail: string;
    };

export interface PlannerModel {
  complete(prompt: string, signal?: AbortSignal): Promise<string>;
}

export class CommandPlanner {
  constructor(private readonly model: PlannerModel) {}

  async plan(prompt: string, signal?: AbortSignal): Promise<PlannerResult> {
    const raw = await this.model.complete(prompt, signal);
    let parsed: unknown;

    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      return {
        ok: false,
        error: "invalid_json",
        detail: error instanceof Error ? error.message : String(error),
      };
    }

    if (!Value.Check(CommandPlanSchema, parsed)) {
      return {
        ok: false,
        error: "schema_invalid",
        detail: "CommandPlanSchema validation failed",
      };
    }

    return { ok: true, plan: parsed };
  }
}
