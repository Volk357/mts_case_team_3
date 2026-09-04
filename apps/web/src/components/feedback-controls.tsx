import { useMutation } from "@tanstack/react-query";
import { Check, ChevronDown, MessageSquareText } from "lucide-react";
import { useState } from "react";

import {
  putFindingFeedback,
  type FeedbackDecision,
  type FindingFeedback,
} from "@/api/feedback";
import { getFeedbackActorKey } from "@/lib/feedback-actor";
import { cn } from "@/lib/utils";

const feedbackOptions: Array<{
  decision: FeedbackDecision;
  label: string;
  description: string;
}> = [
  {
    decision: "accepted",
    label: "Полезно",
    description: "Замечание точное и требует доработки документа.",
  },
  {
    decision: "false_positive",
    label: "Ложная тревога",
    description: "Проблемы нет: система неверно интерпретировала документ.",
  },
  {
    decision: "already_described",
    label: "Уже описано",
    description: "Нужная информация уже есть в другом месте документа.",
  },
  {
    decision: "allowed_exception",
    label: "Допустимое исключение",
    description: "Замечание формально верно, но исключение согласовано.",
  },
  {
    decision: "not_relevant",
    label: "Не относится",
    description: "Правило неприменимо к этому документу или разделу.",
  },
];

export function FeedbackControls({
  findingId,
  savedFeedback,
  onSaved,
}: {
  findingId: string;
  savedFeedback?: FindingFeedback;
  onSaved?: (feedback: FindingFeedback) => void;
}) {
  const [decision, setDecision] = useState<FeedbackDecision | undefined>(
    savedFeedback?.decision,
  );
  const [comment, setComment] = useState(savedFeedback?.comment ?? "");
  const [commentOpen, setCommentOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const feedback = useMutation({
    mutationFn: ({
      nextDecision,
      nextComment,
    }: {
      nextDecision: FeedbackDecision;
      nextComment: string;
    }) =>
      putFindingFeedback(
        findingId,
        getFeedbackActorKey(),
        nextDecision,
        nextComment.trim() || null,
      ),
    onSuccess: (saved) => {
      setDecision(saved.decision);
      setComment(saved.comment ?? "");
      onSaved?.(saved);
    },
  });

  const saveDecision = (nextDecision: FeedbackDecision) => {
    setDecision(nextDecision);
    feedback.mutate({ nextDecision, nextComment: comment });
  };

  return (
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
            onClick={() => saveDecision(option.decision)}
            title={option.description}
            type="button"
          >
            {decision === option.decision && <Check aria-hidden="true" className="size-3.5" />}
            {option.label}
          </button>
        ))}
      </div>

      <button
        aria-expanded={helpOpen}
        className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        onClick={() => setHelpOpen((open) => !open)}
        type="button"
      >
        Что означают варианты?
        <ChevronDown
          aria-hidden="true"
          className={cn("size-3.5 transition-transform", helpOpen && "rotate-180")}
        />
      </button>
      {helpOpen && (
        <dl className="mt-2 grid gap-2 rounded-xl bg-muted/60 p-3 text-xs leading-5">
          {feedbackOptions.map((option) => (
            <div key={option.decision}>
              <dt className="font-semibold">{option.label}</dt>
              <dd className="text-muted-foreground">{option.description}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-3">
        <button
          aria-expanded={commentOpen}
          className="text-xs font-medium text-primary hover:underline"
          onClick={() => setCommentOpen((open) => !open)}
          type="button"
        >
          {savedFeedback?.comment ? "Изменить комментарий" : "Добавить комментарий"}
        </button>
        {savedFeedback?.comment && !commentOpen && (
          <span className="ml-2 text-xs text-muted-foreground">Комментарий сохранён</span>
        )}
        {commentOpen && (
          <div className="mt-2 space-y-2">
            <label className="block text-xs font-medium" htmlFor={`feedback-comment-${findingId}`}>
              Комментарий к оценке
            </label>
            <textarea
              className="min-h-20 w-full resize-y rounded-xl border border-border bg-card px-3 py-2 text-sm focus-visible:border-primary"
              id={`feedback-comment-${findingId}`}
              maxLength={4000}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Необязательно: поясните решение для команды качества"
              value={comment}
            />
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">{comment.length} из 4000</span>
              <button
                className="min-h-9 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
                disabled={!decision || feedback.isPending}
                onClick={() =>
                  decision && feedback.mutate({ nextDecision: decision, nextComment: comment })
                }
                type="button"
              >
                Сохранить комментарий
              </button>
            </div>
            {!decision && (
              <p className="text-xs text-muted-foreground">Сначала выберите оценку замечания.</p>
            )}
          </div>
        )}
      </div>

      <p aria-live="polite" className="mt-2 min-h-5 text-xs text-muted-foreground">
        {feedback.isPending && "Сохраняем оценку…"}
        {feedback.isSuccess && "Оценка сохранена."}
        {feedback.isError && "Не удалось сохранить оценку. Попробуйте ещё раз."}
        {!feedback.isPending && !feedback.isSuccess && !feedback.isError && savedFeedback &&
          "Сохранённая оценка загружена."}
      </p>
    </fieldset>
  );
}
