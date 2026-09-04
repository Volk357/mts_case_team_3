import { CircleAlert, CircleCheck, LoaderCircle, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { getHealth } from "@/api/health";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export function HealthPage() {
  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
  });

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        eyebrow="Диагностика"
        title="Состояние Backend API"
        description="Эта страница проверяет реальное подключение frontend к сервису приложения."
      />

      <Card className="p-6" aria-live="polite">
        {health.isPending && (
          <div className="flex items-center gap-3 text-muted-foreground">
            <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
            Выполняется проверка…
          </div>
        )}

        {health.isSuccess && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 font-semibold text-success">
              <CircleCheck aria-hidden="true" className="size-6" />
              Backend доступен
            </div>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr] sm:gap-y-3">
              <dt className="text-muted-foreground">Сервис</dt>
              <dd className="mb-2 break-all sm:mb-0">{health.data.service}</dd>
              <dt className="text-muted-foreground">Окружение</dt>
              <dd className="mb-2 break-all sm:mb-0">{health.data.environment}</dd>
              <dt className="text-muted-foreground">Версия</dt>
              <dd className="break-all">{health.data.version}</dd>
            </dl>
          </div>
        )}

        {health.isError && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 font-semibold text-danger">
              <CircleAlert aria-hidden="true" className="size-6" />
              Backend недоступен
            </div>
            <p className="text-sm text-muted-foreground">{health.error.message}</p>
            <Button onClick={() => void health.refetch()} size="sm" variant="secondary">
              <RefreshCw aria-hidden="true" className="size-4" />
              Повторить
            </Button>
          </div>
        )}
      </Card>
    </section>
  );
}
