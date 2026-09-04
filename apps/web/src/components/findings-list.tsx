import type { ReviewFinding } from "@/api/reviews";
import { FindingCard } from "@/components/finding-card";

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
        return (
          <li key={finding.finding_id}>
            <FindingCard
              finding={finding}
              onSelect={() => onSelect(finding.finding_id)}
              selected={selected}
            />
          </li>
        );
      })}
    </ol>
  );
}
