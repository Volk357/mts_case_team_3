import { FileText, ListChecks } from "lucide-react";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewFinding } from "@/api/reviews";
import { Card } from "@/components/ui/card";

const severityLabels: Record<ReviewFinding["severity"], string> = {
  critical: "Критические",
  high: "Высокие",
  medium: "Средние",
  low: "Низкие",
};

function findingCountLabel(count: number): string {
  const lastTwoDigits = count % 100;
  if (lastTwoDigits >= 11 && lastTwoDigits <= 14) return "замечаний";
  const lastDigit = count % 10;
  if (lastDigit === 1) return "замечание";
  if (lastDigit >= 2 && lastDigit <= 4) return "замечания";
  return "замечаний";
}

export function ReviewSummary({
  document,
  findings,
}: {
  document: DocumentResponse;
  findings: ReviewFinding[];
}) {
  const severitySummary = Object.entries(severityLabels)
    .map(([severity, label]) => ({
      label,
      count: findings.filter((finding) => finding.severity === severity).length,
    }))
    .filter(({ count }) => count > 0);

  return (
    <Card className="grid gap-5 p-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:p-8">
      <div className="flex min-w-0 gap-4">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <FileText aria-hidden="true" className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted-foreground">Проверенный документ</p>
          <h1 className="mt-1 break-words text-2xl font-semibold tracking-tight sm:text-3xl">
            {document.filename}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {severitySummary.length > 0
              ? severitySummary.map(({ count, label }) => `${label}: ${count}`).join(" · ")
              : "Замечаний по уровням серьёзности нет"}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3 rounded-2xl bg-primary/5 px-5 py-4 text-primary">
        <ListChecks aria-hidden="true" className="size-6 shrink-0" />
        <div>
          <strong className="block text-2xl leading-none">{findings.length}</strong>
          <span className="text-sm font-medium">{findingCountLabel(findings.length)}</span>
        </div>
      </div>
    </Card>
  );
}
