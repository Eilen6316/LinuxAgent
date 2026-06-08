import { type Static, Type } from "typebox";

export const PolicyLevelSchema = Type.Union([
  Type.Literal("SAFE"),
  Type.Literal("CONFIRM"),
  Type.Literal("BLOCK"),
]);

export const PolicyDecisionSchema = Type.Object({
  level: PolicyLevelSchema,
  reason: Type.Union([Type.String(), Type.Null()]),
  riskScore: Type.Number({ minimum: 0, maximum: 100 }),
  capabilities: Type.Array(Type.String()),
  matchedRules: Type.Array(Type.String()),
  neverWhitelist: Type.Boolean(),
});

export type PolicyLevel = Static<typeof PolicyLevelSchema>;
export type PolicyDecision = Static<typeof PolicyDecisionSchema>;
