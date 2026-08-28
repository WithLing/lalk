import { SERVER_URL } from "./endpoint";
import type {
  AppConfig,
  ConfigResponse,
} from "../runtime/contracts";

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${SERVER_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json()) as { detail?: string };
    throw new HttpError(response.status, body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const getConfig = () => request<ConfigResponse>("/api/config");

export const saveConfig = (config: AppConfig) =>
  request<ConfigResponse>("/api/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });

export const getModels = (baseUrl: string, apiKey: string) =>
  request<{ models: string[] }>("/api/models", {
    method: "POST",
    body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
  });
