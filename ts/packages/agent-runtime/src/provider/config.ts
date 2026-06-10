export type ReactProviderName =
  | "openai"
  | "openai_compatible"
  | "deepseek"
  | "ollama"
  | "vllm"
  | "lmstudio"
  | "local";

export interface ReactProviderConfig {
  provider: ReactProviderName;
  model: string;
  baseUrl?: string;
  apiKey?: string;
  tokenParameter?: "max_completion_tokens" | "max_tokens";
}

interface RawReactProviderConfig {
  api?: {
    provider?: unknown;
    model?: unknown;
    base_url?: unknown;
    baseUrl?: unknown;
    api_key?: unknown;
    apiKey?: unknown;
    token_parameter?: unknown;
    tokenParameter?: unknown;
  };
}

const LOCAL_PROVIDERS = new Set<ReactProviderName>(["ollama", "vllm", "lmstudio", "local"]);
const REMOTE_PROVIDERS = new Set<ReactProviderName>(["openai", "openai_compatible", "deepseek"]);

export function validateReactProviderConfig(raw: unknown): ReactProviderConfig {
  if (!raw || typeof raw !== "object" || !("api" in raw)) {
    throw new Error("api provider config is required");
  }
  const api = (raw as RawReactProviderConfig).api;
  if (!api || typeof api !== "object") {
    throw new Error("api provider config is required");
  }

  const provider = requiredString(api.provider, "api.provider") as ReactProviderName;
  if (!isSupportedProvider(provider)) {
    throw new Error(`unsupported api.provider: ${provider}`);
  }
  const model = requiredString(api.model, "api.model");
  const apiKey = optionalString(api.api_key ?? api.apiKey);
  if (REMOTE_PROVIDERS.has(provider) && !apiKey) {
    throw new Error(`api.api_key is required for provider ${provider}`);
  }

  const baseUrl = optionalString(api.base_url ?? api.baseUrl);
  const tokenParameter = optionalTokenParameter(api.token_parameter ?? api.tokenParameter);
  return {
    provider,
    model,
    ...(baseUrl !== undefined ? { baseUrl } : {}),
    ...(apiKey !== undefined ? { apiKey } : {}),
    ...(tokenParameter !== undefined ? { tokenParameter } : {}),
  };
}

export function isLocalReactProvider(provider: ReactProviderName): boolean {
  return LOCAL_PROVIDERS.has(provider);
}

function isSupportedProvider(provider: string): provider is ReactProviderName {
  return (
    LOCAL_PROVIDERS.has(provider as ReactProviderName) ||
    REMOTE_PROVIDERS.has(provider as ReactProviderName)
  );
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${field} is required`);
  }
  return value.trim();
}

function optionalString(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw new Error("optional api string fields must be strings");
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function optionalTokenParameter(value: unknown): ReactProviderConfig["tokenParameter"] | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (value === "max_completion_tokens" || value === "max_tokens") return value;
  throw new Error(`unsupported api.token_parameter: ${String(value)}`);
}
