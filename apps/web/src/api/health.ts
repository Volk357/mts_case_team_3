import { requestJson } from "@/api/client";
import type { HealthResponse } from "@/api/generated";

export type { HealthResponse } from "@/api/generated";

export function getHealth(signal?: AbortSignal) {
  return requestJson<HealthResponse>("/api/health", { signal });
}
