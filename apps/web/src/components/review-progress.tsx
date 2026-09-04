import {
  CheckCircle2,
  Clock3,
  FileClock,
  LoaderCircle,
  ScanSearch,
} from "lucide-react";

import type { ReviewState } from "@/api/reviews";
import { ReviewFailureState } from "@/components/review-failure-state";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LONG_REVIEW_THRESHOLD_MS = 2 * 60 * 1000;

const progressSteps = [
  { stage: "waiting", label: "В очереди", icon: FileClock },
  { stage: "analysis", label: "Анализ документа", icon: ScanSearch },
  { stage: "result_ready", label: "Результат готов", icon: CheckCircle2 },
] as const;

function activeStep(review: ReviewState): number {
  if (review.status === "queued") return 0;
  if (review.status === "running") return 1;
  if (review.status === "completed") return 2;
  return -1;
}

function isLongRunning(review: ReviewState, now: number): boolean {
  if (review.status !== "running") return false;
  const startedAt = Date.parse(review.started_at ?? review.queued_at);
  return Number.isFinite(startedAt) && now - startedAt >= LONG_REVIEW_THRESHOLD_MS;
}

export function ReviewProgress({
  review,
  now,
  correlationId,
}: {
  review: ReviewState;
  now: number;
  correlationId?: string;
}) {
  const currentStep = activeStep(review);
  const failed = ["failed", "timed_out", "cancelled"].includes(review.status);

  return (
    <div className="space-y-6">
      <Card className="p-6 sm:p-8">
        <ol aria-label="Этапы проверки" className="grid gap-4 sm:grid-cols-3">
          {progressSteps.map(({ stage, label, icon: Icon }, index) => {
            const complete = currentStep > index;
            const active = currentStep === index;
            return (
              <li
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex min-h-14 items-center gap-3 rounded-xl border px-4 py-3 text-sm",
                  complete && "border-success/20 bg-success/5 text-success",
                  active && "border-primary/30 bg-primary/5 text-primary",
                  !complete && !active && "border-border text-muted-foreground",
                )}
                key={stage}
              >
                {active && review.status !== "completed" ? (
                  <LoaderCircle aria-hidden="true" className="size-5 shrink-0 animate-spin" />
                ) : (
                  <Icon aria-hidden="true" className="size-5 shrink-0" />
                )}
                <span className="font-medium">{label}</span>
              </li>
            );
          })}
        </ol>
      </Card>

      <div
        aria-atomic="true"
        aria-busy={review.status === "queued" || review.status === "running"}
        aria-live="polite"
        className="min-h-52"
      >
        {review.status === "queued" && (
          <Card className="flex min-h-52 gap-4 p-6 sm:p-8">
            <Clock3 aria-hidden="true" className="mt-0.5 size-6 shrink-0 text-primary" />
            <div>
              <h2 className="font-semibold">Проверка ожидает запуска</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Документ принят. Можно оставить страницу открытой — состояние обновится
                автоматически.
              </p>
            </div>
          </Card>
        )}

        {review.status === "running" && (
          <Card className="flex min-h-52 gap-4 p-6 sm:p-8">
            <ScanSearch aria-hidden="true" className="mt-0.5 size-6 shrink-0 text-primary" />
            <div>
              <h2 className="font-semibold">Идёт анализ документа</h2>
              {isLongRunning(review, now) ? (
                <p className="mt-2 text-sm leading-6 text-warning">
                  Проверка занимает больше обычного, но продолжается. Результат появится здесь
                  автоматически.
                </p>
              ) : (
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Проверяем структуру, полноту и однозначность требований. Обновлять страницу вручную
                  не нужно.
                </p>
              )}
            </div>
          </Card>
        )}

        {review.status === "completed" && (
          <Card className="flex min-h-52 gap-4 border-success/20 p-6 sm:p-8">
            <CheckCircle2 aria-hidden="true" className="mt-0.5 size-7 shrink-0 text-success" />
            <div>
              <h2 className="text-lg font-semibold">Проверка завершена</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Результат готов. Автоматическое обновление остановлено.
              </p>
            </div>
          </Card>
        )}

        {failed && <ReviewFailureState correlationId={correlationId} review={review} />}
      </div>
    </div>
  );
}
