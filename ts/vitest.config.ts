import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/**/*.test.ts", "apps/**/*.test.ts", "parity/**/*.test.ts"],
    environment: "node",
    restoreMocks: true,
    clearMocks: true,
  },
});
