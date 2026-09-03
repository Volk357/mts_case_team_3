import { appConfig } from "@/config";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Array<{ location: string[]; reason: string }>;
  };
}

export function parseApiError(body: unknown): { code?: string; message?: string } {
  if (!body || typeof body !== "object" || !("error" in body)) return {};
  const error = (body as { error?: unknown }).error;
  if (!error || typeof error !== "object") return {};
  const candidate = error as { code?: unknown; message?: unknown };
  return {
    code: typeof candidate.code === "string" ? candidate.code : undefined,
    message:
      typeof candidate.message === "string" && candidate.message.trim()
        ? candidate.message
        : undefined,
  };
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const error = parseApiError(body);
    throw new ApiError(
      error.message ?? `API request failed with status ${response.status}`,
      response.status,
      error.code,
    );
  }

  return (await response.json()) as T;
}
