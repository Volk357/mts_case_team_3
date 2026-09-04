import { useSearchParams } from "react-router-dom";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewFinding, ReviewFindings, ReviewState } from "@/api/reviews";
import { ReviewResultsView } from "@/components/review-results";

const SUPPORTED_COUNTS = new Set([0, 1, 12, 20]);
const LONG_SECTION =
  "Правила формирования витрины ежедневной аналитической отчётности для межрегионального контура";
const LONG_QUOTE =
  "Для каждой записи из таблицы событий необходимо выбрать актуальное состояние абонента с учётом временной зоны источника, повторной доставки сообщения и возможного совпадения временных меток, после чего объединить результат со справочником регионов и сохранить историю изменений.";

const fixtureDocument: DocumentResponse = {
  document_id: "00000000-0000-0000-0000-000000000099",
  filename: "Технические требования к формированию единой витрины данных радиосети.pdf",
  size_bytes: 4_812_903,
  media_type: "application/pdf",
  created_at: "2026-09-04T07:00:00.000Z",
};

const fixtureReview: ReviewState = {
  review_id: "00000000-0000-0000-0000-000000000098",
  document_id: fixtureDocument.document_id,
  review_pack_id: "00000000-0000-0000-0000-000000000097",
  status: "completed",
  stage: "result_ready",
  queued_at: "2026-09-04T07:00:00.000Z",
  started_at: "2026-09-04T07:00:01.000Z",
  finished_at: "2026-09-04T07:01:42.000Z",
  poll_after_ms: null,
  error: null,
};

function fixtureFinding(index: number): ReviewFinding {
  const number = index + 1;
  const severities: ReviewFinding["severity"][] = ["critical", "high", "medium", "low"];
  const quote = index === 0 ? LONG_QUOTE : `Поле metric_value_${number} заполняется по данным источника.`;

  return {
    finding_id: `fixture-finding-${number}`,
    ordinal: number,
    defect_id: index === 0 ? "MISSING_SELECTION_LOGIC" : `COMPANY_RULE_${number}`,
    severity: severities[index % severities.length],
    confidence: 0.97 - index * 0.01,
    location:
      index === 1
        ? { page: null, section_path: [], block_id: `fixture-block-${number}` }
        : {
            page: 14 + index,
            section_path: [LONG_SECTION, `Таблица 7. Поля результирующего набора`, `Строка ${number}`],
            block_id: `fixture-block-${number}`,
            table: "Таблица 7",
            row: number,
            column: `metric_value_${number}`,
          },
    quote,
    problem:
      index === 0
        ? "Не определено, какую запись считать актуальной при одинаковом времени нескольких событий из разных источников."
        : "Для поля не указан источник или однозначное правило вычисления значения.",
    clarification:
      index === 0
        ? "Указать порядок приоритетов источников и дополнительное правило сортировки для одинаковых временных меток."
        : "Уточнить источник, формулу расчёта и поведение при отсутствии исходного значения.",
  };
}

export function ResultsVisualFixturePage() {
  const [searchParams] = useSearchParams();
  const requestedCount = Number(searchParams.get("count") ?? "20");
  const count = SUPPORTED_COUNTS.has(requestedCount) ? requestedCount : 20;
  const findings: ReviewFindings = {
    review_id: fixtureReview.review_id,
    items: Array.from({ length: count }, (_, index) => fixtureFinding(index)),
    total: count,
    warnings: [
      {
        code: "PARTIAL_PARSE",
        message:
          "Две страницы с плотными таблицами обработаны частично; результат необходимо сверить с исходным документом.",
      },
    ],
  };

  return <ReviewResultsView document={fixtureDocument} findings={findings} review={fixtureReview} />;
}
