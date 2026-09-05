import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, LoaderCircle } from "lucide-react";

import { getReviewFeedback, type FindingFeedback } from "@/api/feedback";
import { getReview, getReviewFindings, type ReviewFinding, type ReviewState } from "@/api/reviews";
import { FindingCard } from "@/components/finding-card";
import { currentActorKey } from "@/lib/actor-key";

/** Порядок важен: по нему рисуется список шагов на экране ожидания. */
const STAGES = [
  { key: "waiting", title: "Документ в очереди" },
  { key: "analysis", title: "Читаем документ" },
  { key: "result_ready", title: "Собираем замечания" },
] as const;

type Filter = "all" | "high" | "medium" | "low";

/** Секунды с открытия страницы. Тикает раз в секунду, а не раз в опрос. */
function useElapsedSeconds(active: boolean) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (!active) return;
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setSeconds(Math.round((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [active]);

  return seconds;
}

export function ReviewPage() {
  const { reviewId = "" } = useParams();
  const [review, setReview] = useState<ReviewState | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [feedbackByFindingId, setFeedbackByFindingId] = useState<
    Record<string, FindingFeedback>
  >({});

  // Один ключ на всю страницу: оценки этого браузера должны прийти от одного
  // отправителя, иначе их не отличить от оценок другого человека.
  const actorKey = useMemo(() => currentActorKey(), []);

  const load = useCallback(async () => {
    const state = await getReview(reviewId);
    setReview(state);
    if (state.status === "completed") {
      const findingsResponse = await getReviewFindings(reviewId);
      setFindings(findingsResponse.items);
      try {
        const feedback = await getReviewFeedback(reviewId, actorKey);
        setFeedbackByFindingId(
          Object.fromEntries(feedback.items.map((item) => [item.finding_id, item])),
        );
      } catch {
        // Результаты проверки остаются доступны, даже если оценки временно не загрузились.
      }
    }
    return state;
  }, [actorKey, reviewId]);

  useEffect(() => {
    let stop = false;
    let timer: number | undefined;

    async function tick() {
      try {
        const state = await load();
        if (stop) return;
        if (state.status === "queued" || state.status === "running") {
          timer = window.setTimeout(tick, state.poll_after_ms ?? 2000);
        }
      } catch {
        if (!stop) setError("Не удалось получить состояние проверки.");
      }
    }

    void tick();
    return () => {
      stop = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [load]);

  const running = review !== null && (review.status === "queued" || review.status === "running");
  const seconds = useElapsedSeconds(running || review === null);

  const counts = useMemo(() => {
    const list = findings ?? [];
    return {
      all: list.length,
      high: list.filter((f) => f.severity === "high" || f.severity === "critical").length,
      medium: list.filter((f) => f.severity === "medium").length,
      low: list.filter((f) => f.severity === "low").length,
    };
  }, [findings]);

  const visible = useMemo(() => {
    const list = findings ?? [];
    if (filter === "all") return list;
    if (filter === "high") {
      return list.filter((f) => f.severity === "high" || f.severity === "critical");
    }
    return list.filter((f) => f.severity === filter);
  }, [findings, filter]);

  if (error) {
    return <Notice title="Проверка недоступна" text={error} />;
  }

  if (!review) {
    return <Notice title="Открываем проверку" text="Секунду." spinning />;
  }

  if (review.status === "failed" || review.status === "timed_out") {
    return (
      <Notice
        title={review.status === "timed_out" ? "Проверка не уложилась во время" : "Проверка не удалась"}
        text={
          review.error?.message ??
          "Попробуйте запустить ещё раз. Если повторится — напишите администратору контура."
        }
      >
        <Link
          className="mt-6 inline-flex h-11 items-center gap-2 rounded-(--radius-sm) border border-border bg-card px-4 text-[0.9375rem] font-medium transition-colors hover:border-border-hover"
          to="/"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          К загрузке документа
        </Link>
      </Notice>
    );
  }

  if (review.status !== "completed") {
    return <ProgressNotice stage={review.stage} seconds={seconds} />;
  }

  return (
    <div className="space-y-8">
      <header className="space-y-4 sm:space-y-5">
        <Link
          className="-mx-2 inline-flex h-11 items-center gap-2 rounded-(--radius-sm) px-2 text-sm font-medium text-text-secondary transition-colors hover:text-accent sm:h-10"
          to="/"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Проверить другой документ
        </Link>
        <div>
          <h1 className="text-title font-semibold">
            {counts.all === 0 ? "Замечаний нет" : `Замечаний: ${counts.all}`}
          </h1>
          <p className="mt-2 text-[0.9375rem] leading-7 text-text-secondary">
            Каждое замечание — дословная цитата из документа. Решение принимает аналитик:
            отметьте лишнее, и проверка подстроится под ваши соглашения.
          </p>
        </div>
      </header>

      {counts.all > 0 ? (
        <nav
          aria-label="Фильтр по важности"
          className="flex flex-wrap gap-2"
        >
          <FilterTab active={filter} count={counts.all} label="Все" onSelect={setFilter} value="all" />
          <FilterTab active={filter} count={counts.high} label="Высокая" onSelect={setFilter} value="high" />
          <FilterTab active={filter} count={counts.medium} label="Средняя" onSelect={setFilter} value="medium" />
          <FilterTab active={filter} count={counts.low} label="Уточнения" onSelect={setFilter} value="low" />
        </nav>
      ) : null}

      {counts.all === 0 ? (
        <p className="text-[0.9375rem] leading-7 text-text-secondary">
          Инструмент не нашёл мест, требующих уточнения. Это не гарантия: он проверяет
          формальную полноту и типовые смысловые пробелы, а не корректность расчётов.
        </p>
      ) : (
        <div className="space-y-4">
          {visible.map((finding) => (
            <FindingCard
              actorKey={actorKey}
              finding={finding}
              key={finding.finding_id}
              onFeedbackSaved={(saved) =>
                setFeedbackByFindingId((current) => ({
                  ...current,
                  [saved.finding_id]: saved,
                }))
              }
              savedFeedback={feedbackByFindingId[finding.finding_id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Анализ идёт больше минуты. Крутилка с одной строкой за это время читается
 * как зависание, поэтому показываем, какой шаг идёт сейчас и сколько прошло.
 * Никакого поддельного процента: шаги приходят из состояния проверки.
 */
function ProgressNotice({ stage, seconds }: { stage: ReviewState["stage"]; seconds: number }) {
  // stage "finished" приходит на короткое время до status "completed":
  // тогда пройдены все шаги, а не ни одного.
  const found = STAGES.findIndex((item) => item.key === stage);
  const current = stage === "finished" ? STAGES.length : found === -1 ? 0 : found;

  return (
    <div className="mx-auto max-w-md py-12 sm:py-20">
      <h1 className="text-title font-semibold">Проверяем документ</h1>
      {/* Счётчик секунд не озвучиваем: раз в секунду это спам в скринридере.
          Вслух сообщаем только смену шага. */}
      <p className="mt-2 text-[0.9375rem] leading-7 text-text-secondary">
        Обычно занимает около минуты. Прошло {seconds} с.
      </p>
      <p className="sr-only" role="status">
        {STAGES[current]?.title ?? "Проверка завершена"}
      </p>

      <ol className="mt-8 space-y-4">
        {STAGES.map((item, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <li className="flex items-center gap-3" key={item.key}>
              <span
                aria-hidden="true"
                className={`grid size-6 shrink-0 place-items-center rounded-full ${
                  done ? "bg-accent-soft text-accent" : active ? "text-accent" : "text-text-muted"
                }`}
              >
                {done ? (
                  <Check className="size-3.5" />
                ) : active ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <span className="size-1.5 rounded-full bg-current" />
                )}
              </span>
              <span
                className={`text-[0.9375rem] ${
                  active ? "font-medium" : done ? "text-text-secondary" : "text-text-muted"
                }`}
              >
                {item.title}
              </span>
            </li>
          );
        })}
      </ol>

      <p className="mt-8 text-sm leading-6 text-text-muted">
        Страницу можно не держать открытой в фокусе — проверка идёт на сервере.
      </p>
    </div>
  );
}

function FilterTab({
  active,
  count,
  label,
  onSelect,
  value,
}: {
  active: Filter;
  count: number;
  label: string;
  onSelect: (value: Filter) => void;
  value: Filter;
}) {
  const selected = active === value;
  return (
    <button
      aria-pressed={selected}
      className={`inline-flex h-11 shrink-0 items-center gap-2 rounded-(--radius-sm) border px-3.5 text-sm font-medium transition-colors sm:h-9 ${
        selected
          ? "border-accent bg-accent-soft text-accent"
          : "border-border bg-card text-text-secondary hover:border-border-hover disabled:opacity-50"
      }`}
      disabled={count === 0 && value !== "all"}
      onClick={() => onSelect(value)}
      type="button"
    >
      {label}
      <span className={selected ? "text-accent" : "text-text-muted"}>{count}</span>
    </button>
  );
}

function Notice({
  title,
  text,
  spinning,
  children,
}: {
  title: string;
  text: string;
  spinning?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-md py-12 text-center sm:py-20">
      {spinning ? (
        <LoaderCircle aria-hidden="true" className="mx-auto mb-5 size-6 animate-spin text-accent" />
      ) : null}
      <h1 className="text-title font-semibold">{title}</h1>
      <p className="mt-2 text-[0.9375rem] leading-7 text-text-secondary">{text}</p>
      {children}
    </div>
  );
}
