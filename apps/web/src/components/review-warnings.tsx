import { TriangleAlert } from "lucide-react";

import type { ReviewWarning } from "@/api/generated";
import { Card } from "@/components/ui/card";

export function ReviewWarnings({ warnings }: { warnings: ReviewWarning[] }) {
  if (warnings.length === 0) return null;

  return (
    <Card className="border-warning/30 bg-warning/5 p-5" role="status">
      <div className="flex gap-3">
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-warning" />
        <div className="min-w-0">
          <h2 className="font-semibold">Документ обработан с предупреждениями</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Некоторые части документа могли быть распознаны не полностью. Учитывайте это при ручной
            проверке результата.
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {warnings.map((warning, index) => (
              <li className="break-words" key={`${warning.code ?? "warning"}-${index}`}>
                {warning.code && (
                  <code className="mr-2 rounded bg-warning/10 px-1.5 py-0.5 text-xs text-warning">
                    {warning.code}
                  </code>
                )}
                {warning.message}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
