import { describe, expect, it, vi } from "vitest";
import {
  type ReactProviderConfig,
  resolvePiModelDescriptor,
  validateReactProviderConfig,
} from "../../src/provider/index.js";

describe("resolvePiModelDescriptor", () => {
  it("resolves openai-compatible config without a network call", () => {
    const descriptor = resolvePiModelDescriptor(
      validateReactProviderConfig({
        api: {
          provider: "openai_compatible",
          base_url: "https://llm.example.test/v1",
          model: "ops-model",
          api_key: "config-secret",
          token_parameter: "max_tokens",
        },
      }),
    );

    expect(descriptor).toEqual({
      provider: "openai_compatible",
      piProvider: "openai",
      api: "openai-completions",
      model: "ops-model",
      baseUrl: "https://llm.example.test/v1",
      apiKey: "config-secret",
      tokenParameter: "max_tokens",
      local: false,
    });
  });

  it("rejects missing apiKey for remote providers", () => {
    expect(() =>
      validateReactProviderConfig({
        api: {
          provider: "openai",
          model: "gpt-test",
          api_key: "",
        },
      }),
    ).toThrow(/api_key is required/);
  });

  it("allows local providers without apiKey", () => {
    const config = validateReactProviderConfig({
      api: {
        provider: "ollama",
        base_url: "http://127.0.0.1:11434",
        model: "llama3.1",
        api_key: "",
      },
    });

    expect(resolvePiModelDescriptor(config)).toMatchObject({
      provider: "ollama",
      piProvider: "ollama",
      model: "llama3.1",
      local: true,
    });
  });

  it("does not allow environment variables to override config secrets", () => {
    vi.stubEnv("OPENAI_API_KEY", "env-secret");
    const config: ReactProviderConfig = validateReactProviderConfig({
      api: {
        provider: "openai",
        model: "gpt-test",
        api_key: "config-secret",
      },
    });

    expect(resolvePiModelDescriptor(config).apiKey).toBe("config-secret");

    vi.unstubAllEnvs();
  });
});
