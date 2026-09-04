import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export function FindingsNavigation({
  currentIndex,
  total,
  onPrevious,
  onNext,
}: {
  currentIndex: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const hasSelection = currentIndex >= 0 && total > 0;

  return (
    <nav
      aria-label="Навигация по замечаниям"
      className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-3 py-2"
    >
      <Button
        aria-label="Предыдущее замечание"
        disabled={!hasSelection || currentIndex === 0}
        onClick={onPrevious}
        size="sm"
        type="button"
        variant="ghost"
      >
        <ChevronLeft aria-hidden="true" className="size-4" />
        <span className="hidden sm:inline">Предыдущее</span>
      </Button>
      <span aria-live="polite" className="text-center text-xs font-medium text-muted-foreground">
        {hasSelection ? `${currentIndex + 1} из ${total}` : "Нет замечаний"}
      </span>
      <Button
        aria-label="Следующее замечание"
        disabled={!hasSelection || currentIndex === total - 1}
        onClick={onNext}
        size="sm"
        type="button"
        variant="ghost"
      >
        <span className="hidden sm:inline">Следующее</span>
        <ChevronRight aria-hidden="true" className="size-4" />
      </Button>
    </nav>
  );
}
