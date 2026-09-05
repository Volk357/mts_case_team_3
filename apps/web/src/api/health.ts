import { requestJson } from "@/api/client";

/** Состояние отдельной зависимости: сервис не «жив/мёртв», а готов или нет. */
export type CheckStatus = "ok" | "failed";

export interface HealthResponse {
  /**
   * `degraded` означает, что процесс отвечает, но обслужить проверку не может:
   * например лежит база или остановился воркер. Считать это состояние
   * здоровым нельзя — как предполётная проверка перед демонстрацией оно
   * тогда не значит ничего.
   */
  status: "ok" | "degraded";
  service: string;
  environment: "development" | "test" | "demo" | "production";
  version: string;
  checks: Record<string, CheckStatus>;
}

export function getHealth(signal?: AbortSignal) {
  return requestJson<HealthResponse>("/api/health", { signal });
}
