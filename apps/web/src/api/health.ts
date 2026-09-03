import { requestJson } from "@/api/client";

export interface HealthResponse {
  status: "ok";
  service: string;
  environment: "development" | "test" | "demo" | "production";
  version: string;
}

export function getHealth(signal?: AbortSignal) {
  return requestJson<HealthResponse>("/api/health", { signal });
}
