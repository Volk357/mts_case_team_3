import { appConfig } from "@/config";
import type { ErrorEnvelope } from "@/api/generated";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly correlationId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ApiErrorEnvelope = ErrorEnvelope;

export interface ApiResponse<T> {
  data: T;
  correlationId?: string;
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

export async function requestJsonWithMetadata<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResponse<T>> {
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
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }

  return {
    data: (await response.json()) as T,
    correlationId: response.headers.get("X-Correlation-ID") ?? undefined,
  };
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  return (await requestJsonWithMetadata<T>(path, init)).data;
}
