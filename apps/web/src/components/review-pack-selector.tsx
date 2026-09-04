import { useQuery } from "@tanstack/react-query";
import { CircleAlert, LoaderCircle, RefreshCw, Settings2 } from "lucide-react";

import { getReviewPacks } from "@/api/review-packs";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface ReviewPackSelectorProps {
  value: string;
  onChange: (reviewPackId: string) => void;
}

export function ReviewPackSelector({ value, onChange }: ReviewPackSelectorProps) {
  const catalog = useQuery({
    queryKey: ["review-packs"],
    queryFn: ({ signal }) => getReviewPacks(signal),
  });

  if (catalog.isPending) {
    return (
      <Card aria-live="polite" className="flex items-center gap-3 p-6 text-muted-foreground">
        <LoaderCircle aria-hidden="true" className="size-5 animate-spin" />
        Загружаем профили проверки…
      </Card>
    );
  }

  if (catalog.isError) {
    return (
      <Card className="space-y-4 p-6" role="alert">
        <div className="flex gap-3 text-danger">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
          <div>
            <h2 className="font-semibold">Профили проверки недоступны</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Не удалось получить правила проверки. Повторите запрос.
            </p>
          </div>
        </div>
        <Button onClick={() => void catalog.refetch()} size="sm" type="button" variant="secondary">
          <RefreshCw aria-hidden="true" className="size-4" />
          Повторить
        </Button>
      </Card>
    );
  }

  const selected = catalog.data.items.find((item) => item.review_pack_id === value);

  return (
    <Card className="p-6 sm:p-8">
      <div className="flex gap-4">
        <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <Settings2 aria-hidden="true" className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <label className="font-semibold" htmlFor="review-pack">
            Профиль проверки
          </label>
          <p className="mt-1 text-sm leading-6 text-muted-foreground" id="review-pack-help">
            Выберите набор правил, соответствующий типу документа вашей организации.
          </p>
          {catalog.data.total > 0 ? (
            <>
              <select
                aria-describedby="review-pack-help"
                className="mt-4 h-11 w-full rounded-xl border border-border bg-card px-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                id="review-pack"
                onChange={(event) => onChange(event.target.value)}
                value={value}
              >
                <option value="">Выберите профиль</option>
                {catalog.data.items.map((item) => (
                  <option key={item.review_pack_id} value={item.review_pack_id}>
                    {item.display_name} · {item.version}
                  </option>
                ))}
              </select>
              {selected && (
                <p className="mt-3 text-sm text-muted-foreground">
                  Тип документа: {selected.document_type}
                </p>
              )}
            </>
          ) : (
            <p className="mt-4 rounded-xl bg-warning/10 px-4 py-3 text-sm text-warning">
              Нет доступных профилей проверки. Обратитесь к администратору продукта.
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
