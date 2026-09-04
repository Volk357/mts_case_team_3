import { useState } from "react";
import { Check, LoaderCircle, X } from "lucide-react";

import { putFindingFeedback, type FeedbackDecision } from "@/api/feedback";
import { defectTitle } from "@/lib/defect-titles";
import type { ReviewFinding } from "@/api/reviews";

const SEVERITY = {
  critical: { label: "Критично", dot: "bg-red", text: "text-red", tint: "bg-red-soft" },
  high: { label: "Высокая", dot: "bg-red", text: "text-red", tint: "bg-red-soft" },
  medium: { label: "Средняя", dot: "bg-amber", text: "text-amber", tint: "bg-amber-soft" },
  low: { label: "Уточнение", dot: "bg-gold", text: "text-gold", tint: "bg-gold-soft" },
} as const;

interface FindingCardProps {
  finding: ReviewFinding;
  actorKey: string;
}

export function FindingCard({ finding, actorKey }: FindingCardProps) {
  const [decision, setDecision] = useState<FeedbackDecision | null>(null);
  const [pending, setPending] = useState<FeedbackDecision | null>(null);
  const [failed, setFailed] = useState(false);

  const severity = SEVERITY[finding.severity] ?? SEVERITY.medium;
  const section = finding.location.section_path.filter(Boolean).join(" · ");

  async function rate(next: FeedbackDecision) {
    setPending(next);
    setFailed(false);
    try {
      await putFindingFeedback(finding.finding_id, actorKey, next);
      setDecision(next);
    } catch {
      setFailed(true);
    } finally {
      setPending(null);
    }
  }

  return (
    <article className="rounded-(--radius-card) border border-border bg-card shadow-xs transition-shadow hover:shadow-card">
      <div className="px-4 pt-4 sm:px-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`inline-flex items-center gap-2 text-sm font-medium ${severity.text}`}>
            <span aria-hidden="true" className={`size-1.5 rounded-full ${severity.dot}`} />
            {severity.label}
          </span>
          {section ? <span className="text-sm text-text-muted">{section}</span> : null}
        </div>
        <h3 className="mt-1.5 text-[0.9375rem] leading-6 font-semibold">
          {defectTitle(finding.defect_id)}
        </h3>
      </div>

      <blockquote className="mx-4 mt-3.5 overflow-x-auto overscroll-x-contain rounded-(--radius-sm) bg-background-subtle px-4 py-3 sm:mx-5">
        <p className="font-mono text-[0.8125rem] leading-6 whitespace-pre-wrap text-navy-mid">
          {finding.quote}
        </p>
      </blockquote>

      <div className="space-y-2 px-4 pt-4 sm:px-5">
        <p className="text-[0.9375rem] leading-7">{finding.problem}</p>
        <p className="text-[0.9375rem] leading-7 text-text-secondary">
          <span className="font-medium text-accent">Что уточнить. </span>
          {finding.clarification}
        </p>
      </div>

      <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-border-light px-4 py-3 sm:px-5">
        {decision ? (
          <p className="text-sm text-text-secondary">
            {decision === "accepted" ? "Отмечено как полезное" : "Отмечено как лишнее"}
            {". "}
            <button
              className="font-medium text-accent underline-offset-4 hover:underline"
              onClick={() => setDecision(null)}
              type="button"
            >
              Изменить
            </button>
          </p>
        ) : (
          <>
            <RateButton
              icon={Check}
              label="Полезно"
              onClick={() => void rate("accepted")}
              pending={pending === "accepted"}
            />
            <RateButton
              icon={X}
              label="Не по делу"
              onClick={() => void rate("false_positive")}
              pending={pending === "false_positive"}
            />
            <span className="ml-auto hidden text-sm text-text-muted sm:inline">
              Оценка настраивает проверку под ваши соглашения
            </span>
          </>
        )}
        {failed ? (
          <p className="w-full text-sm text-red" role="alert">
            Оценка не сохранилась. Проверьте связь и нажмите ещё раз.
          </p>
        ) : null}
      </footer>
    </article>
  );
}

function RateButton({
  icon: Icon,
  label,
  onClick,
  pending,
}: {
  icon: typeof Check;
  label: string;
  onClick: () => void;
  pending: boolean;
}) {
  return (
    <button
      className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-(--radius-sm) border border-border bg-card px-3.5 text-sm font-medium transition-colors hover:border-border-hover hover:bg-background-subtle disabled:opacity-60 sm:h-9 sm:flex-none sm:justify-start"
      disabled={pending}
      onClick={onClick}
      type="button"
    >
      {pending ? (
        <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
      ) : (
        <Icon aria-hidden="true" className="size-4 text-text-muted" />
      )}
      {label}
    </button>
  );
}
