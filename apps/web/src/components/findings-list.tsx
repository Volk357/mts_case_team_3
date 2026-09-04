import { MapPin } from "lucide-react";

import type { ReviewFinding } from "@/api/reviews";
import { cn } from "@/lib/utils";

const severityLabels: Record<ReviewFinding["severity"], string> = {
  critical: "Критическое",
  high: "Высокое",
  medium: "Среднее",
  low: "Низкое",
};

export function FindingsList({
  findings,
  selectedFindingId,
  onSelect,
}: {
  findings: ReviewFinding[];
  selectedFindingId?: string;
  onSelect: (findingId: string) => void;
}) {
  if (findings.length === 0) {
    return (
      <div className="rounded-card border border-dashed border-border bg-card p-6 text-sm text-muted-foreground">
        По выбранным фильтрам замечаний нет.
      </div>
    );
  }

  return (
    <ol aria-label="Замечания" className="space-y-3">
      {findings.map((finding) => {
        const selected = finding.finding_id === selectedFindingId;
        const section = finding.location.section_path.at(-1);
        return (
          <li key={finding.finding_id}>
            <button
              aria-pressed={selected}
              className={cn(
                "w-full rounded-card border bg-card p-5 text-left shadow-sm transition hover:border-primary/40",
                selected ? "border-primary ring-2 ring-primary/15" : "border-border",
              )}
              onClick={() => onSelect(finding.finding_id)}
              type="button"
            >
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold tracking-wide text-primary uppercase">
                  {severityLabels[finding.severity]}
                </span>
                <span className="text-xs text-muted-foreground">#{finding.ordinal}</span>
              </span>
              <strong className="mt-2 block break-words text-sm">{finding.defect_id}</strong>
              <span className="mt-2 line-clamp-2 block text-sm leading-6 text-muted-foreground">
                {finding.problem}
              </span>
              <span className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <MapPin aria-hidden="true" className="size-3.5 shrink-0" />
                <span className="truncate">
                  {section ?? (finding.location.page ? `Страница ${finding.location.page}` : "Место уточняется")}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
