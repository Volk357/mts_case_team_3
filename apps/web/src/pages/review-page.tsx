import { useQuery } from "@tanstack/react-query";
import { CircleAlert, LoaderCircle, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { getReview } from "@/api/reviews";
import { PageHeader } from "@/components/page-header";
import { ReviewProgress } from "@/components/review-progress";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const TERMINAL_STATUSES = new Set(["completed", "failed", "timed_out", "cancelled"]);

export function ReviewPage() {
  const { reviewId = "" } = useParams();
  const review = useQuery({
    queryKey: ["reviews", reviewId],
    queryFn: ({ signal }) => getReview(reviewId, signal),
    enabled: Boolean(reviewId),
    refetchInterval: (query) => {
      const snapshot = query.state.data;
      if (!snapshot || TERMINAL_STATUSES.has(snapshot.status)) return false;
      return snapshot.poll_after_ms ?? 2_000;
    },
  });

  return (
    <section className="mx-auto max-w-4xl space-y-8">
      <PageHeader
        eyebrow="Проверка документа"
        title="Следим за ходом анализа"
        description="Страница обновляется автоматически. Её можно перезагрузить или открыть позднее — идентификатор проверки сохранён в адресе."
      />

      {review.isPending && (
        <Card aria-live="polite" className="flex items-center gap-3 p-8 text-muted-foreground">
          <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
          Получаем состояние проверки…
        </Card>
      )}

      {review.isError && (
        <Card className="space-y-5 p-6 sm:p-8" role="alert">
          <div className="flex gap-3">
            <CircleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-danger" />
            <div>
              <h2 className="font-semibold">Не удалось получить состояние проверки</h2>
              <p className="mt-2 text-sm text-muted-foreground">{review.error.message}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => void review.refetch()} size="sm" type="button">
              <RefreshCw aria-hidden="true" className="size-4" />
              Повторить
            </Button>
            <Button asChild size="sm" variant="secondary">
              <Link to="/">Вернуться на главную</Link>
            </Button>
          </div>
        </Card>
      )}

      {review.isSuccess && <ReviewProgress now={review.dataUpdatedAt} review={review.data} />}

      <p className="text-xs text-muted-foreground">
        ID проверки: <code>{reviewId}</code>
      </p>
    </section>
  );
}
