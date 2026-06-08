import { type Static, Type } from "typebox";

export const RuntimeEventSchema = Type.Object({
  type: Type.String({ minLength: 1 }),
  threadId: Type.Optional(Type.String()),
  commandId: Type.Optional(Type.String()),
  payload: Type.Record(Type.String(), Type.Unknown()),
});

export type RuntimeEvent = Static<typeof RuntimeEventSchema>;
