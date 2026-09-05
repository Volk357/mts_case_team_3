import { ArrowLeft, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getReviews, type ReviewListItem, type ReviewStatus } from "@/api/reviews";

/*
  История проверок. Без неё человек, загрузивший второй документ, терял ссылку
  на первый: вернуться можно было только по сохранённому адресу. Для теста
  у заказчика это критично — он приносит несколько своих ТЗ подряд.
*/

const STATUS_LABELS: Record<ReviewStatus, string> = {
  queued: "В очереди",
  running: "Идёт проверка",
  completed: "Готово",
  failed: "Не удалась",
  timed_out: "Не уложилась во время",
  cancelled: "Отменена",
};

/** Дата в виде «5 сентября, 10:23» — год не нужен, история короткая. */
function formatMoment(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** «12 замечаний» с правильным окончанием: список читают, а не парсят. */
function findingsLabel(count: number): string {
  const tail = count % 10;
  const teen = count % 100;
  if (teen >= 11 && teen <= 14) return `${count} замечаний`;
  if (tail === 1) return `${count} замечание`;
  if (tail >= 2 && tail <= 4) return `${count} замечания`;
  return `${count} замечаний`;
}

export function ReviewsPage() {
  const [items, setItems] = useState<ReviewListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const list = await getReviews(controller.signal);
        setItems(list.items);
      } catch (cause) {
        // Уход со страницы отменяет запрос — это не ошибка для человека.
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError("Не удалось загрузить список проверок. Обновите страницу.");
      }
    })();
    return () => controller.abort();
  }, []);

  return (
    <div className="space-y-8">
      <header className="space-y-4 sm:space-y-5">
        <Link
          className="-mx-2 inline-flex h-11 items-center gap-2 rounded-(--radius-sm) px-2 text-sm font-medium text-text-secondary transition-colors hover:text-accent sm:h-10"
          to="/"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Проверить документ
        </Link>
        <div>
          <h1 className="text-title font-semibold">Проверки</h1>
          <p className="mt-2 text-[0.9375rem] leading-7 text-text-secondary">
            Загруженные документы и их результаты. Оценки замечаний сохраняются — к любой
            проверке можно вернуться.
          </p>
        </div>
      </header>

      {error ? <p className="text-[0.9375rem] leading-7 text-text-secondary">{error}</p> : null}

      {!items && !error ? (
        <p className="flex items-center gap-2 text-[0.9375rem] text-text-secondary">
          <LoaderCircle aria-hidden="true" className="size-4 animate-spin text-accent" />
          Загружаем список.
        </p>
      ) : null}

      {items?.length === 0 ? (
        <p className="text-[0.9375rem] leading-7 text-text-secondary">
          Проверок пока нет. Загрузите документ — он появится здесь.
        </p>
      ) : null}

      {items && items.length > 0 ? (
        <ul className="divide-y divide-border overflow-hidden rounded-(--radius-card) border border-border bg-card">
          {items.map((item) => (
            <li key={item.review_id}>
              <Link
                className="flex min-h-16 flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-4 transition-colors hover:bg-muted/50 sm:px-5"
                to={`/reviews/${item.review_id}`}
              >
                <span className="min-w-0 flex-1">
                  {/* Имя файла может быть длинным и без пробелов — переносим
                      по символам, иначе строка распирает список на телефоне. */}
                  <span className="block font-medium break-words">{item.document_filename}</span>
                  <span className="mt-0.5 block text-sm text-text-secondary">
                    {formatMoment(item.queued_at)}
                  </span>
                </span>
                <span className="shrink-0 text-sm text-text-secondary">
                  {item.status === "completed"
                    ? findingsLabel(item.findings_count)
                    : STATUS_LABELS[item.status]}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
