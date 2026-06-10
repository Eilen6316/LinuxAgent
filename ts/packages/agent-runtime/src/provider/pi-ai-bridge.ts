import { isLocalReactProvider, type ReactProviderConfig } from "./config.js";

export interface PiModelDescriptor {
  provider: ReactProviderConfig["provider"];
  piProvider: string;
  api: string;
  model: string;
  local: boolean;
  baseUrl?: string;
  apiKey?: string;
  tokenParameter?: ReactProviderConfig["tokenParameter"];
}

export function resolvePiModelDescriptor(config: ReactProviderConfig): PiModelDescriptor {
  const local = isLocalReactProvider(config.provider);
  return {
    provider: config.provider,
    piProvider: piProvider(config.provider),
    api: piApi(config.provider),
    model: config.model,
    local,
    ...(config.baseUrl !== undefined ? { baseUrl: config.baseUrl } : {}),
    ...(config.apiKey !== undefined ? { apiKey: config.apiKey } : {}),
    ...(config.tokenParameter !== undefined ? { tokenParameter: config.tokenParameter } : {}),
  };
}

function piProvider(provider: ReactProviderConfig["provider"]): string {
  switch (provider) {
    case "openai":
    case "openai_compatible":
      return "openai";
    case "deepseek":
      return "deepseek";
    case "ollama":
    case "vllm":
    case "lmstudio":
    case "local":
      return provider;
  }
}

function piApi(provider: ReactProviderConfig["provider"]): string {
  switch (provider) {
    case "openai":
    case "openai_compatible":
    case "deepseek":
    case "vllm":
    case "lmstudio":
    case "local":
      return "openai-completions";
    case "ollama":
      return "openai-completions";
  }
}
