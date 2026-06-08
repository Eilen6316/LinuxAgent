export interface RedactionResult {
  text: string;
  redacted: boolean;
  truncated: boolean;
}

const PATTERNS: RegExp[] = [
  /Bearer\s+[A-Za-z0-9._~+/=-]+/g,
  /sk-[A-Za-z0-9_-]{16,}/g,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
];

export function redactOutput(input: string, maxChars = 12000): RedactionResult {
  let text = input;
  let redacted = false;
  for (const pattern of PATTERNS) {
    text = text.replace(pattern, () => {
      redacted = true;
      return "[REDACTED]";
    });
  }
  const truncated = text.length > maxChars;
  if (truncated) text = `${text.slice(0, maxChars)}\n[TRUNCATED]`;
  return { text, redacted, truncated };
}
