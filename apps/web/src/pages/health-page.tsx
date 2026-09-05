import { CircleAlert, CircleCheck, LoaderCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getHealth, type HealthResponse } from "@/api/health";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type HealthState =
  | { kind: "loading" }
  | { kind: "ready"; data: HealthResponse }
  | { kind: "error"; message: string };

export function HealthPage() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  const loadHealth = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getHealth(signal);
      setState({ kind: "ready", data });
    } catch (error) {
      if (signal?.aborted) return;
      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "Неизвестная ошибка",
      });
    }
  }, []);

  const retry = () => {
    setState({ kind: "loading" });
    void loadHealth();
  };

  useEffect(() => {
    const controller = new AbortController();
    void getHealth(controller.signal)
      .then((data) => setState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "Неизвестная ошибка",
        });
      });
    return () => controller.abort();
  }, []);

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <p className="mb-2 text-sm font-medium text-primary">Диагностика</p>
        <h1 className="text-title font-semibold">Состояние Backend API</h1>
        <p className="mt-3 text-muted-foreground">
          Эта страница проверяет реальное подключение frontend к сервису приложения.
        </p>
      </div>

      <Card className="p-5 sm:p-6" aria-live="polite">
        {state.kind === "loading" && (
          <div className="flex items-center gap-3 text-muted-foreground">
            <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
            Выполняется проверка…
          </div>
        )}

        {state.kind === "ready" && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 font-semibold text-green">
              <CircleCheck aria-hidden="true" className="size-6" />
              Backend доступен
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-3 text-sm">
              <dt className="text-muted-foreground">Сервис</dt>
              <dd>{state.data.service}</dd>
              <dt className="text-muted-foreground">Окружение</dt>
              <dd>{state.data.environment}</dd>
              <dt className="text-muted-foreground">Версия</dt>
              <dd>{state.data.version}</dd>
            </dl>
          </div>
        )}

        {state.kind === "error" && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 font-semibold text-red">
              <CircleAlert aria-hidden="true" className="size-6" />
              Backend недоступен
            </div>
            <p className="text-sm text-muted-foreground">{state.message}</p>
            <Button onClick={retry} size="sm" variant="secondary">
              <RefreshCw aria-hidden="true" className="size-4" />
              Повторить
            </Button>
          </div>
        )}
      </Card>
    </section>
  );
}
