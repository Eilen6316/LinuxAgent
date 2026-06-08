import { type Static, Type } from "typebox";

export const FilePatchPlanSchema = Type.Object({
  version: Type.Literal(1),
  requestIntent: Type.Union([
    Type.Literal("create"),
    Type.Literal("update"),
    Type.Literal("unknown"),
  ]),
  summary: Type.String(),
  patches: Type.Array(
    Type.Object({
      path: Type.String({ minLength: 1 }),
      diff: Type.String({ minLength: 1 }),
    }),
  ),
  permissionChanges: Type.Optional(
    Type.Array(
      Type.Object({
        path: Type.String({ minLength: 1 }),
        mode: Type.String({ pattern: "^[0-7]{3,4}$" }),
      }),
    ),
  ),
});

export type FilePatchPlan = Static<typeof FilePatchPlanSchema>;
