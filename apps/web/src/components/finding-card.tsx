import { useMutation } from "@tanstack/react-query";
import { Check, ChevronRight, MapPin, MessageSquareText } from "lucide-react";
import { useState, type KeyboardEventHandler, type Ref } from "react";

import { putFindingFeedback, type FeedbackDecision } from "@/api/feedback";
import type { ReviewFinding } from "@/api/reviews";
import { getFeedbackActorKey } from "@/lib/feedback-actor";
import { cn } from "@/lib/utils";

const severityPresentation: Record<
  ReviewFinding["severity"],
  { label: string; className: string }
> = {
  critical: { label: "Критическое", className: "bg-danger/10 text-danger" },
  high: { label: "Высокое", className: "bg-warning/10 text-warning" },
  medium: { label: "Среднее", className: "bg-primary/10 text-primary" },
  low: { label: "Низкое", className: "bg-muted text-muted-foreground" },
};

const feedbackOptions: Array<{ decision: FeedbackDecision; label: string }> = [
  { decision: "accepted", label: "Полезно" },
  { decision: "false_positive", label: "Ложная тревога" },
  { decision: "already_described", label: "Уже описано" },
  { decision: "allowed_exception", label: "Допустимое исключение" },
  { decision: "not_relevant", label: "Не относится" },
];

export function FindingCard({
  finding,
  selected,
  onSelect,
  selectionButtonId,
  selectionButtonRef,
  selectionTabIndex,
  onSelectionKeyDown,
}: {
  finding: ReviewFinding;
  selected: boolean;
  onSelect: () => void;
  selectionButtonId?: string;
  selectionButtonRef?: Ref<HTMLButtonElement>;
  selectionTabIndex?: number;
  onSelectionKeyDown?: KeyboardEventHandler<HTMLButtonElement>;
}) {
  const [decision, setDecision] = useState<FeedbackDecision>();
  const feedback = useMutation({
    mutationFn: (nextDecision: FeedbackDecision) =>
      putFindingFeedback(finding.finding_id, getFeedbackActorKey(), nextDecision),
    onSuccess: (saved) => setDecision(saved.decision),
  });
  const severity = severityPresentation[finding.severity];
  const locationParts = finding.location.section_path;
  const locationLabel = finding.location.page
    ? `Страница ${finding.location.page}`
    : locationParts.length > 0
      ? "Раздел документа"
      : "Поиск по цитате";

  return (
    <article
      className={cn(
        "overflow-hidden rounded-card border bg-card shadow-sm transition",
        selected ? "border-primary ring-2 ring-primary/15" : "border-border",
      )}
    >
      <button
        aria-pressed={selected}
        className="w-full p-5 text-left hover:bg-muted/30"
        id={selectionButtonId}
        onClick={onSelect}
        onKeyDown={onSelectionKeyDown}
        ref={selectionButtonRef}
        tabIndex={selectionTabIndex}
        type="button"
      >
        <span className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", severity.className)}>
            {severity.label}
          </span>
          <span className="text-xs text-muted-foreground">Замечание #{finding.ordinal}</span>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <MapPin aria-hidden="true" className="size-3.5" />
            {locationLabel}
          </span>
        </span>

        <strong className="mt-3 block break-words text-sm">{finding.defect_id}</strong>

        {locationParts.length > 0 && (
          <span className="mt-3 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            {locationParts.map((part, index) => (
              <span className="contents" key={`${part}-${index}`}>
                {index > 0 && <ChevronRight aria-hidden="true" className="size-3 shrink-0" />}
                <span className="break-words">{part}</span>
              </span>
            ))}
          </span>
        )}

        <span className="mt-4 block border-l-4 border-primary/25 pl-4 text-sm leading-6 text-muted-foreground">
          <span className="sr-only">Цитата: </span>«{finding.quote}»
        </span>

        <span className="mt-5 block">
          <span className="block text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Возможная проблема
          </span>
          <span className="mt-1 block break-words text-sm leading-6">{finding.problem}</span>
        </span>

        <span className="mt-4 block rounded-xl bg-primary/5 px-4 py-3">
          <span className="block text-xs font-semibold tracking-wide text-primary uppercase">
            Что требуется уточнить
          </span>
          <span className="mt-1 block break-words text-sm leading-6">{finding.clarification}</span>
        </span>
      </button>

      <fieldset className="border-t border-border px-5 py-4" disabled={feedback.isPending}>
        <legend className="flex items-center gap-2 px-1 text-xs font-medium text-muted-foreground">
          <MessageSquareText aria-hidden="true" className="size-3.5" />
          Оцените замечание
        </legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {feedbackOptions.map((option) => (
            <button
              aria-pressed={decision === option.decision}
              className={cn(
                "inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition",
                decision === option.decision
                  ? "border-success/30 bg-success/10 text-success"
                  : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              key={option.decision}
              onClick={() => feedback.mutate(option.decision)}
              type="button"
            >
              {decision === option.decision && <Check aria-hidden="true" className="size-3.5" />}
              {option.label}
            </button>
          ))}
        </div>
        <p aria-live="polite" className="mt-2 min-h-5 text-xs text-muted-foreground">
          {feedback.isPending && "Сохраняем оценку…"}
          {feedback.isSuccess && "Оценка сохранена."}
          {feedback.isError && "Не удалось сохранить оценку. Попробуйте ещё раз."}
        </p>
      </fieldset>
    </article>
  );
}
