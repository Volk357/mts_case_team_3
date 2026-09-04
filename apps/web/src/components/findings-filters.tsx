import type { ReviewFinding } from "@/api/reviews";
import { Card } from "@/components/ui/card";

export type SeverityFilter = ReviewFinding["severity"] | "all";

const severityOptions: Array<{ value: SeverityFilter; label: string }> = [
  { value: "all", label: "Все уровни" },
  { value: "critical", label: "Критические" },
  { value: "high", label: "Высокие" },
  { value: "medium", label: "Средние" },
  { value: "low", label: "Низкие" },
];

export function FindingsFilters({
  severity,
  defectType,
  defectTypes,
  onSeverityChange,
  onDefectTypeChange,
}: {
  severity: SeverityFilter;
  defectType: string;
  defectTypes: string[];
  onSeverityChange: (value: SeverityFilter) => void;
  onDefectTypeChange: (value: string) => void;
}) {
  return (
    <Card className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
      <label className="text-sm font-medium">
        Уровень серьёзности
        <select
          className="mt-2 h-11 w-full rounded-xl border border-border bg-card px-3 text-sm focus-visible:border-primary"
          onChange={(event) => onSeverityChange(event.target.value as SeverityFilter)}
          value={severity}
        >
          {severityOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm font-medium">
        Тип дефекта
        <select
          className="mt-2 h-11 w-full rounded-xl border border-border bg-card px-3 text-sm focus-visible:border-primary"
          onChange={(event) => onDefectTypeChange(event.target.value)}
          value={defectType}
        >
          <option value="all">Все типы</option>
          {defectTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </label>
    </Card>
  );
}
