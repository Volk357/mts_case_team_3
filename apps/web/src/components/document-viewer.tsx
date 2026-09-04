import { ExternalLink, FileSearch2, LocateFixed } from "lucide-react";
import type { CSSProperties } from "react";

import { getDocumentContentUrl, type DocumentResponse } from "@/api/documents";
import type { ReviewFinding } from "@/api/reviews";
import { Card } from "@/components/ui/card";
import { buildPdfViewerUrl, normalizeHighlightBox } from "@/lib/document-location";

const PDF_MEDIA_TYPE = "application/pdf";
const DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function PdfViewer({ document, finding }: { document: DocumentResponse; finding?: ReviewFinding }) {
  const viewerUrl = buildPdfViewerUrl(document.document_id, finding);
  const highlight = normalizeHighlightBox(finding?.location.bbox);
  const highlightStyle: CSSProperties | undefined = highlight
    ? {
        left: `${highlight.left}%`,
        top: `${highlight.top}%`,
        width: `${highlight.width}%`,
        height: `${highlight.height}%`,
      }
    : undefined;

  return (
    <>
      <div className="relative min-h-[34rem] bg-muted/50">
        <iframe
          className="absolute inset-0 size-full border-0 bg-card"
          key={viewerUrl}
          loading="lazy"
          src={viewerUrl}
          title={`Просмотр документа ${document.filename}`}
        />
        {highlightStyle && (
          <span
            aria-label="Область выбранного замечания"
            className="pointer-events-none absolute z-10 min-h-3 min-w-3 border-2 border-danger bg-danger/20 shadow-[0_0_0_3px_rgb(255_255_255/0.8)]"
            role="img"
            style={highlightStyle}
          />
        )}
      </div>
      {finding && (
        <div className="flex gap-3 border-t border-border bg-card px-5 py-4 text-sm text-muted-foreground">
          <LocateFixed aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>
            {highlight
              ? "Область замечания подсвечена по координатам анализа."
              : "Точная координатная подсветка недоступна. Выполнен переход к странице и поиск по цитате."}
          </p>
        </div>
      )}
    </>
  );
}

function DocxFallback({ document, finding }: { document: DocumentResponse; finding?: ReviewFinding }) {
  return (
    <div className="grid min-h-[34rem] place-items-center bg-muted/35 p-6">
      <div className="w-full max-w-xl rounded-2xl border border-border bg-card p-6 shadow-sm">
        <FileSearch2 aria-hidden="true" className="size-8 text-primary" />
        <h3 className="mt-4 font-semibold">Текстовый просмотр DOCX</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Браузер не поддерживает точное отображение DOCX. Ниже показан фрагмент, найденный во время
          анализа.
        </p>
        {finding ? (
          <>
            {finding.location.section_path.length > 0 && (
              <p className="mt-5 break-words text-sm font-semibold">
                {finding.location.section_path.join(" → ")}
              </p>
            )}
            <blockquote className="mt-3 break-words border-l-4 border-primary/30 pl-4 text-sm leading-6 text-muted-foreground">
              «{finding.quote}»
            </blockquote>
            <p className="mt-4 text-xs text-warning">
              Точная подсветка в DOCX недоступна; положение указано по разделу и текстовой цитате.
            </p>
          </>
        ) : (
          <p className="mt-5 text-sm text-muted-foreground">Выберите замечание слева.</p>
        )}
        <a
          className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl border border-border px-4 py-2 text-sm font-semibold hover:bg-muted"
          href={getDocumentContentUrl(document.document_id)}
          rel="noreferrer"
          target="_blank"
        >
          Открыть исходный DOCX
          <ExternalLink aria-hidden="true" className="size-4" />
        </a>
      </div>
    </div>
  );
}

export function DocumentViewer({
  document,
  finding,
}: {
  document: DocumentResponse;
  finding?: ReviewFinding;
}) {
  const isPdf = document.media_type === PDF_MEDIA_TYPE;
  const isDocx = document.media_type === DOCX_MEDIA_TYPE;

  return (
    <Card className="min-h-[38rem] overflow-hidden lg:sticky lg:top-6">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Просмотр документа</h2>
          <p className="mt-1 truncate text-xs text-muted-foreground" title={document.filename}>
            {document.filename}
          </p>
        </div>
        {finding?.location.page && (
          <span className="shrink-0 rounded-lg bg-muted px-2.5 py-1 text-xs font-medium">
            Страница {finding.location.page}
          </span>
        )}
      </div>

      {isPdf && <PdfViewer document={document} finding={finding} />}
      {isDocx && <DocxFallback document={document} finding={finding} />}
      {!isPdf && !isDocx && (
        <div className="grid min-h-[34rem] place-items-center p-6 text-center text-sm text-muted-foreground">
          Просмотр этого формата недоступен.
        </div>
      )}
    </Card>
  );
}
