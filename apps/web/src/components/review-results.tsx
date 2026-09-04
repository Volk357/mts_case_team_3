import { useQuery } from "@tanstack/react-query";
import { CircleAlert, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getDocument } from "@/api/documents";
import { getReviewFindings, type ReviewFinding, type ReviewState } from "@/api/reviews";
import { DocumentViewer } from "@/components/document-viewer";
import { FindingsFilters, type SeverityFilter } from "@/components/findings-filters";
import { FindingsList } from "@/components/findings-list";
import { ReviewSummary } from "@/components/review-summary";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const EMPTY_FINDINGS: ReviewFinding[] = [];

export function ReviewResults({ review }: { review: ReviewState }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [defectType, setDefectType] = useState("all");
  const document = useQuery({
    queryKey: ["documents", review.document_id],
    queryFn: ({ signal }) => getDocument(review.document_id, signal),
    retry: false,
  });
  const findings = useQuery({
    queryKey: ["reviews", review.review_id, "findings"],
    queryFn: ({ signal }) => getReviewFindings(review.review_id, signal),
    retry: false,
  });

  const allFindings = findings.data?.items ?? EMPTY_FINDINGS;
  const defectTypes = useMemo(
    () => [...new Set(allFindings.map((finding) => finding.defect_id))].sort(),
    [allFindings],
  );
  const filteredFindings = useMemo(
    () =>
      allFindings.filter(
        (finding) =>
          (severity === "all" || finding.severity === severity) &&
          (defectType === "all" || finding.defect_id === defectType),
      ),
    [allFindings, defectType, severity],
  );
  const requestedFindingId = searchParams.get("finding") ?? undefined;
  const selectedFinding =
    filteredFindings.find((finding) => finding.finding_id === requestedFindingId) ??
    filteredFindings[0];

  useEffect(() => {
    const nextFindingId = selectedFinding?.finding_id;
    if (!nextFindingId || nextFindingId === requestedFindingId) return;
    const next = new URLSearchParams(searchParams);
    next.set("finding", nextFindingId);
    setSearchParams(next, { replace: true });
  }, [requestedFindingId, searchParams, selectedFinding?.finding_id, setSearchParams]);

  const selectFinding = (findingId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("finding", findingId);
    setSearchParams(next, { replace: true });
  };

  if (document.isPending || findings.isPending) {
    return (
      <Card aria-live="polite" className="flex items-center gap-3 p-8 text-muted-foreground">
        <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
        Загружаем результаты проверки…
      </Card>
    );
  }

  if (document.isError || findings.isError) {
    return (
      <Card className="space-y-5 p-6 sm:p-8" role="alert">
        <div className="flex gap-3">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-danger" />
          <div>
            <h1 className="font-semibold">Не удалось загрузить результат</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Повторите запрос. Состояние завершённой проверки сохранено.
            </p>
          </div>
        </div>
        <Button
          onClick={() => void Promise.all([document.refetch(), findings.refetch()])}
          size="sm"
          type="button"
          variant="secondary"
        >
          <RefreshCw aria-hidden="true" className="size-4" />
          Повторить
        </Button>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <ReviewSummary document={document.data} findings={allFindings} />
      <FindingsFilters
        defectType={defectType}
        defectTypes={defectTypes}
        onDefectTypeChange={setDefectType}
        onSeverityChange={setSeverity}
        severity={severity}
      />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)]">
        <section aria-labelledby="findings-title" className="min-w-0">
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <h2 className="text-lg font-semibold" id="findings-title">
              Замечания
            </h2>
            <span aria-live="polite" className="text-sm text-muted-foreground">
              Показано: {filteredFindings.length} из {allFindings.length}
            </span>
          </div>
          <FindingsList
            findings={filteredFindings}
            onSelect={selectFinding}
            selectedFindingId={selectedFinding?.finding_id}
          />
        </section>
        <DocumentViewer document={document.data} finding={selectedFinding} />
      </div>
    </div>
  );
}
