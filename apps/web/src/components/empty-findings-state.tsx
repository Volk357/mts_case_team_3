import { CircleCheck } from "lucide-react";

import { Card } from "@/components/ui/card";

export function EmptyFindingsState() {
  return (
    <Card className="grid min-h-56 place-items-center border-success/25 bg-success/5 p-8 text-center">
      <div className="max-w-md">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-success/10 text-success">
          <CircleCheck aria-hidden="true" className="size-6" />
        </span>
        <h2 className="mt-4 text-xl font-semibold">Замечаний не найдено</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Автоматическая проверка завершена без замечаний. Перед публикацией документа сохраните
          обычную ручную проверку.
        </p>
      </div>
    </Card>
  );
}
