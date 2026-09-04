import { useQuery } from "@tanstack/react-query";
import { CircleAlert, Info, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { getDocument, type DocumentResponse } from "@/api/documents";
import {
  getReviewFindings,
  type ReviewFinding,
  type ReviewFindings,
  type ReviewState,
} from "@/api/reviews";
import { DocumentViewer } from "@/components/document-viewer";
import { EmptyFindingsState } from "@/components/empty-findings-state";
import { FindingsFilters, type SeverityFilter } from "@/components/findings-filters";
import { FindingsList } from "@/components/findings-list";
import { FindingsNavigation } from "@/components/findings-navigation";
import { ReviewSummary } from "@/components/review-summary";
import { ReviewWarnings } from "@/components/review-warnings";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

const EMPTY_FINDINGS: ReviewFinding[] = [];

export function ReviewResults({ review }: { review: ReviewState }) {
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

  return <ReviewResultsView document={document.data} findings={findings.data} review={review} />;
}

export function ReviewResultsView({
  review,
  document,
  findings,
}: {
  review: ReviewState;
  document: DocumentResponse;
  findings: ReviewFindings;
}) {
  const findingsViewport = useRef<HTMLDivElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [severity, setSeverity] = useState<SeverityFilter>("all");
  const [defectType, setDefectType] = useState("all");
  const allFindings = findings.items ?? EMPTY_FINDINGS;
  const warnings = findings.warnings ?? [];
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
  const selectedFindingIndex = selectedFinding
    ? filteredFindings.findIndex((finding) => finding.finding_id === selectedFinding.finding_id)
    : -1;
  const scrollStorageKey = `docreview.findings-scroll.${review.review_id}`;

  useEffect(() => {
    const nextFindingId = selectedFinding?.finding_id;
    if (!nextFindingId || nextFindingId === requestedFindingId) return;
    const next = new URLSearchParams(searchParams);
    next.set("finding", nextFindingId);
    setSearchParams(next, { replace: true });
  }, [requestedFindingId, searchParams, selectedFinding?.finding_id, setSearchParams]);

  useEffect(() => {
    const viewport = findingsViewport.current;
    if (!viewport) return;

    try {
      const savedPosition = Number.parseInt(sessionStorage.getItem(scrollStorageKey) ?? "0", 10);
      if (Number.isFinite(savedPosition)) viewport.scrollTop = savedPosition;
    } catch {
      // Results remain usable when browser storage is unavailable.
    }
  }, [scrollStorageKey]);

  const selectFinding = (findingId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("finding", findingId);
    setSearchParams(next, { replace: true });
  };

  const selectAtIndex = (index: number) => {
    const finding = filteredFindings[index];
    if (finding) selectFinding(finding.finding_id);
  };

  const rememberScrollPosition = (event: UIEvent<HTMLDivElement>) => {
    try {
      sessionStorage.setItem(scrollStorageKey, String(event.currentTarget.scrollTop));
    } catch {
      // Scrolling does not depend on storage availability.
    }
  };

  return (
    <div className="space-y-6">
      <ReviewSummary document={document} findings={allFindings} />
      <ReviewWarnings warnings={warnings} />
      {allFindings.length === 0 ? (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)]">
          <EmptyFindingsState />
          <DocumentViewer document={document} />
        </div>
      ) : (
        <>
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
              <FindingsNavigation
                currentIndex={selectedFindingIndex}
                onNext={() => selectAtIndex(selectedFindingIndex + 1)}
                onPrevious={() => selectAtIndex(selectedFindingIndex - 1)}
                total={filteredFindings.length}
              />
              {allFindings.length >= 20 && (
                <p className="mb-3 flex gap-2 rounded-xl bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground">
                  <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                  Показаны первые 20 замечаний — это установленный лимит одного результата проверки.
                </p>
              )}
              <div
                aria-label="Прокручиваемый список замечаний"
                className="overscroll-contain lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto lg:pr-2"
                onScroll={rememberScrollPosition}
                ref={findingsViewport}
              >
                <FindingsList
                  findings={filteredFindings}
                  onSelect={selectFinding}
                  selectedFindingId={selectedFinding?.finding_id}
                />
              </div>
            </section>
            <DocumentViewer document={document} finding={selectedFinding} />
          </div>
        </>
      )}
    </div>
  );
}
