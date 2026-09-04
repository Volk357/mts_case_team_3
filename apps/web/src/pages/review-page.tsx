import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, LoaderCircle } from "lucide-react";

import { getReview, getReviewFindings, type ReviewFinding, type ReviewState } from "@/api/reviews";
import { FindingCard } from "@/components/finding-card";

/** Ключ отправителя оценок: неперсональный, нужен API обратной связи. */
const ACTOR_KEY = "web-ui";

const STAGE_TEXT: Record<string, string> = {
  waiting: "Документ в очереди",
  analysis: "Читаем документ",
  result_ready: "Собираем замечания",
  finished: "Готово",
};

type Filter = "all" | "high" | "medium" | "low";

export function ReviewPage() {
  const { reviewId = "" } = useParams();
  const [review, setReview] = useState<ReviewState | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const startedAt = useRef(Date.now());

  const load = useCallback(async () => {
    const state = await getReview(reviewId);
    setReview(state);
    if (state.status === "completed") {
      setFindings((await getReviewFindings(reviewId)).items);
    }
    return state;
  }, [reviewId]);

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
      />
    );
  }

  if (review.status !== "completed") {
    const seconds = Math.round((Date.now() - startedAt.current) / 1000);
    return (
      <Notice
        title={STAGE_TEXT[review.stage] ?? "Проверяем документ"}
        text={`Обычно занимает около минуты. Прошло ${seconds} с.`}
        spinning
      />
    );
  }

  return (
    <div className="space-y-8">
      <header className="space-y-5">
        <Link
          className="inline-flex items-center gap-2 text-sm font-medium text-text-secondary transition-colors hover:text-accent"
          to="/"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Проверить другой документ
        </Link>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {counts.all === 0 ? "Замечаний нет" : `Замечаний: ${counts.all}`}
          </h1>
          <p className="mt-2 max-w-2xl text-[0.9375rem] leading-7 text-text-secondary">
            Каждое замечание — дословная цитата из документа. Решение принимает аналитик:
            отметьте лишнее, и проверка подстроится под ваши соглашения.
          </p>
        </div>
      </header>

      {counts.all > 0 ? (
        <nav aria-label="Фильтр по важности" className="flex flex-wrap gap-2">
          <FilterTab active={filter} count={counts.all} label="Все" onSelect={setFilter} value="all" />
          <FilterTab active={filter} count={counts.high} label="Высокая" onSelect={setFilter} value="high" />
          <FilterTab active={filter} count={counts.medium} label="Средняя" onSelect={setFilter} value="medium" />
          <FilterTab active={filter} count={counts.low} label="Уточнения" onSelect={setFilter} value="low" />
        </nav>
      ) : null}

      {counts.all === 0 ? (
        <p className="max-w-2xl text-[0.9375rem] leading-7 text-text-secondary">
          Инструмент не нашёл мест, требующих уточнения. Это не гарантия: он проверяет
          формальную полноту и типовые смысловые пробелы, а не корректность расчётов.
        </p>
      ) : (
        <div className="space-y-4">
          {visible.map((finding) => (
            <FindingCard actorKey={ACTOR_KEY} finding={finding} key={finding.finding_id} />
          ))}
        </div>
      )}
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
      className={`inline-flex h-9 items-center gap-2 rounded-(--radius-sm) border px-3.5 text-sm font-medium transition-colors ${
        selected
          ? "border-accent bg-accent-soft text-accent"
          : "border-border bg-card text-text-secondary hover:border-border-hover"
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

function Notice({ title, text, spinning }: { title: string; text: string; spinning?: boolean }) {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      {spinning ? (
        <LoaderCircle aria-hidden="true" className="mx-auto mb-5 size-6 animate-spin text-accent" />
      ) : null}
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-[0.9375rem] leading-7 text-text-secondary">{text}</p>
    </div>
  );
}
