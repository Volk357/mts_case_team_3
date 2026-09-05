import { ArrowLeft, LoaderCircle, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/api/client";
import { deleteDocument } from "@/api/documents";
import { getReviews, type ReviewListItem, type ReviewStatus } from "@/api/reviews";

/*
  История проверок. Без неё человек, загрузивший второй документ, терял ссылку
  на первый: вернуться можно было только по сохранённому адресу. Для теста
  у заказчика это критично — он приносит несколько своих ТЗ подряд.

  Отсюда же убираются ненужные файлы. Удаление стирает исходник, но оставляет
  замечания и оценки: это собранная разметка, а не копия документа.
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

function removalErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return "Идёт проверка этого документа — удалите после неё.";
    if (error.status === 404) return "Файл уже удалён.";
  }
  return "Не удалось удалить файл. Попробуйте ещё раз.";
}

export function ReviewsPage() {
  const [items, setItems] = useState<ReviewListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Подтверждение держим на строке, а не в модальном окне: удаление здесь
  // не катастрофично (замечания остаются), а диалог посреди списка мешает.
  // Ключ — review_id, а не document_id: один документ могли проверять
  // несколько раз, и по document_id подтверждение раскрылось бы сразу во
  // всех его строках, с несколькими autoFocus одновременно.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [removalError, setRemovalError] = useState<string | null>(null);

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

  const remove = async (item: ReviewListItem) => {
    setRemoving(item.review_id);
    setRemovalError(null);
    try {
      await deleteDocument(item.document_id);
      // Из списка уходят все проверки этого документа, а не только эта строка:
      // на сервере скрыт сам документ, и повторный запрос вернул бы то же.
      setItems((current) =>
        (current ?? []).filter((row) => row.document_id !== item.document_id),
      );
      setConfirming(null);
    } catch (cause) {
      setRemovalError(removalErrorMessage(cause));
    } finally {
      setRemoving(null);
    }
  };

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
            Загруженные документы и их результаты. Файл можно удалить — замечания и
            ваши оценки при этом сохранятся.
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
            <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-5" key={item.review_id}>
              <Link
                className="-mx-2 flex min-h-11 min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-(--radius-sm) px-2 transition-colors hover:bg-muted/50"
                to={`/reviews/${item.review_id}`}
              >
                <span className="min-w-0 flex-1">
                  {/* Имя файла может быть длинным и без пробелов — переносим
                      по символам, иначе строка распирает список на телефоне. */}
                  <span className="block font-medium break-words">{item.document_filename}</span>
                  <span className="mt-0.5 block text-sm text-text-secondary">
                    {item.review_pack_name} · версия {item.review_pack_version}
                  </span>
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

              {confirming === item.review_id ? (
                <span
                  className="flex shrink-0 items-center gap-2"
                  onKeyDown={(event) => {
                    // Escape — привычный выход из подтверждения; без него
                    // передумать можно только мышью.
                    if (event.key === "Escape") setConfirming(null);
                  }}
                >
                  <button
                    autoFocus
                    className="inline-flex h-11 items-center rounded-(--radius-sm) bg-red px-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 sm:h-9"
                    disabled={removing === item.review_id}
                    onClick={() => void remove(item)}
                    type="button"
                  >
                    {removing === item.review_id ? "Удаляем…" : "Удалить файл"}
                  </button>
                  <button
                    className="inline-flex h-11 items-center rounded-(--radius-sm) px-3 text-sm font-medium text-text-secondary transition-colors hover:text-foreground sm:h-9"
                    onClick={() => setConfirming(null)}
                    type="button"
                  >
                    Отмена
                  </button>
                </span>
              ) : (
                <button
                  aria-label={`Удалить файл ${item.document_filename}`}
                  className="inline-flex size-11 shrink-0 items-center justify-center rounded-(--radius-sm) text-text-secondary transition-colors hover:bg-muted hover:text-red sm:size-9"
                  onClick={() => {
                    setConfirming(item.review_id);
                    setRemovalError(null);
                  }}
                  type="button"
                >
                  <Trash2 aria-hidden="true" className="size-4" />
                </button>
              )}

              {removalError && confirming === item.review_id ? (
                <p
                  className="w-full rounded-(--radius-sm) bg-red-soft px-3 py-2 text-sm leading-6 text-red"
                  role="alert"
                >
                  {removalError}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
