import { appConfig } from "@/config";
import { currentToken } from "@/auth/session";

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

/** Заголовок авторизации, если вход выполнен. Проверяет его nginx на /api/. */
export function authHeaders(): Record<string, string> {
  const token = currentToken();
  return token ? { Authorization: `Basic ${token}` } : {};
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...authHeaders(),
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
