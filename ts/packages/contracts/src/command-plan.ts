import { type Static, Type } from "typebox";

export const CommandSourceSchema = Type.Union([
  Type.Literal("llm"),
  Type.Literal("operator"),
  Type.Literal("runbook"),
]);

export const CommandPlanStepSchema = Type.Object({
  id: Type.String({ minLength: 1 }),
  argv: Type.Array(Type.String(), { minItems: 1 }),
  source: CommandSourceSchema,
  reason: Type.String({ minLength: 1 }),
  sandboxProfile: Type.Optional(Type.String()),
});

export const CommandPlanSchema = Type.Object({
  version: Type.Literal(1),
  summary: Type.String(),
  steps: Type.Array(CommandPlanStepSchema),
});

export type CommandSource = Static<typeof CommandSourceSchema>;
export type CommandPlanStep = Static<typeof CommandPlanStepSchema>;
export type CommandPlan = Static<typeof CommandPlanSchema>;
