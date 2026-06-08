import { type Static, Type } from "typebox";

export const AuditEntrySchema = Type.Object({
  timestamp: Type.String({ minLength: 1 }),
  eventType: Type.String({ minLength: 1 }),
  payload: Type.Record(Type.String(), Type.Unknown()),
  prevHash: Type.Union([Type.String(), Type.Null()]),
  hash: Type.String({ minLength: 64, maxLength: 64 }),
});

export type AuditEntry = Static<typeof AuditEntrySchema>;
