import { FileSearch2 } from "lucide-react";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewFinding } from "@/api/reviews";
import { Card } from "@/components/ui/card";

export function DocumentPreview({
  document,
  finding,
}: {
  document: DocumentResponse;
  finding?: ReviewFinding;
}) {
  return (
    <Card className="min-h-[32rem] overflow-hidden lg:sticky lg:top-6">
      <div className="border-b border-border px-5 py-4 sm:px-6">
        <p className="text-sm font-semibold">Область просмотра документа</p>
        <p className="mt-1 truncate text-xs text-muted-foreground" title={document.filename}>
          {document.filename}
        </p>
      </div>
      <div className="grid min-h-[26rem] place-items-center bg-muted/35 p-6">
        {finding ? (
          <div className="w-full max-w-xl rounded-2xl border border-border bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>{finding.location.page ? `Страница ${finding.location.page}` : "Страница не указана"}</span>
              <span>Замечание #{finding.ordinal}</span>
            </div>
            {finding.location.section_path.length > 0 && (
              <p className="mt-4 break-words text-sm font-semibold">
                {finding.location.section_path.join(" → ")}
              </p>
            )}
            <blockquote className="mt-4 break-words border-l-4 border-primary/30 pl-4 text-sm leading-6 text-muted-foreground">
              {finding.quote}
            </blockquote>
          </div>
        ) : (
          <div className="max-w-sm text-center text-muted-foreground">
            <FileSearch2 aria-hidden="true" className="mx-auto size-9" />
            <p className="mt-4 font-medium text-foreground">Выберите замечание</p>
            <p className="mt-2 text-sm leading-6">
              Здесь будет показано соответствующее место документа.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
