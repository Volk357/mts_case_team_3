import type { FindingFeedback } from "@/api/feedback";
import { FeedbackControls } from "@/components/feedback-controls";
import { defectTitle } from "@/lib/defect-titles";
import type { ReviewFinding } from "@/api/reviews";

/**
 * Чем найдено замечание. Это наш сильный аргумент, и до сих пор его на экране
 * не было видно: детерминированный слой на эталоне даёт 96% против 82% у модели
 * и не выдумывает цитат. Формулировка короткая — строка и так несёт важность
 * и раздел; `null` (слой неизвестен) не пишем вовсе.
 */
const DETECTION_LABEL = {
  rule: "по правилу",
  model: "моделью",
  mixed: "правилом и моделью",
} as const;

const SEVERITY = {
  critical: { label: "Критично", dot: "bg-red", text: "text-red", tint: "bg-red-soft" },
  high: { label: "Высокая", dot: "bg-red", text: "text-red", tint: "bg-red-soft" },
  medium: { label: "Средняя", dot: "bg-amber", text: "text-amber", tint: "bg-amber-soft" },
  low: { label: "Уточнение", dot: "bg-gold", text: "text-gold", tint: "bg-gold-soft" },
} as const;

interface FindingCardProps {
  finding: ReviewFinding;
  actorKey: string;
  savedFeedback?: FindingFeedback;
  onFeedbackSaved?: (feedback: FindingFeedback) => void;
}

export function FindingCard({
  finding,
  actorKey,
  savedFeedback,
  onFeedbackSaved,
}: FindingCardProps) {
  const severity = SEVERITY[finding.severity] ?? SEVERITY.medium;
  const section = finding.location.section_path.filter(Boolean).join(" · ");

  return (
    <article className="rounded-(--radius-card) border border-border bg-card shadow-xs transition-shadow hover:shadow-card">
      <div className="px-4 pt-4 sm:px-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`inline-flex items-center gap-2 text-sm font-medium ${severity.text}`}>
            <span aria-hidden="true" className={`size-1.5 rounded-full ${severity.dot}`} />
            {severity.label}
          </span>
          {section ? <span className="text-sm text-text-muted">{section}</span> : null}
          {finding.detection_layer ? (
            <span className="text-sm text-text-muted sm:ml-auto">
              найдено {DETECTION_LABEL[finding.detection_layer]}
            </span>
          ) : null}
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

      <FeedbackControls
        actorKey={actorKey}
        findingId={finding.finding_id}
        onSaved={onFeedbackSaved}
        savedFeedback={savedFeedback}
      />
    </article>
  );
}
