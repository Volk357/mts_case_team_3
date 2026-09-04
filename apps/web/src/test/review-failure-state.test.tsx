import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { ReviewState } from "@/api/reviews";
import { ReviewFailureState } from "@/components/review-failure-state";

const failedReview: ReviewState = {
  review_id: "review-failed",
  document_id: "document-1",
  review_pack_id: "pack-1",
  status: "failed",
  stage: "finished",
  queued_at: "2026-09-04T07:00:00Z",
  started_at: "2026-09-04T07:00:01Z",
  finished_at: "2026-09-04T07:00:10Z",
  poll_after_ms: null,
  error: { code: "INTERNAL_ERROR", message: "safe backend message", retriable: false },
};

it.each([
  ["CORE_PROCESS_FAILED", "Модуль анализа недоступен"],
  ["MODEL_UNAVAILABLE", "Модель анализа временно недоступна"],
  ["ANALYSIS_TIMEOUT", "Превышено время проверки"],
  ["CORE_SCHEMA_INCOMPATIBLE", "Версия результата не поддерживается"],
  ["REVIEW_PACK_NOT_FOUND", "Профиль проверки недоступен"],
])("renders an actionable state for %s", (code, title) => {
  render(
    <MemoryRouter>
      <ReviewFailureState
        review={{ ...failedReview, error: { code, message: "technical detail", retriable: false } }}
      />
    </MemoryRouter>,
  );

  expect(screen.getByRole("heading", { name: title })).toBeVisible();
  expect(screen.getByRole("link", { name: "Запустить новую проверку" })).toHaveAttribute(
    "href",
    "/",
  );
  expect(screen.queryByText("technical detail")).not.toBeInTheDocument();
});

it("shows a correlation ID for an unknown terminal error", () => {
  render(
    <MemoryRouter>
      <ReviewFailureState
        correlationId="corr-unknown-42"
        review={{
          ...failedReview,
          error: { code: "FUTURE_ERROR", message: "private detail", retriable: false },
        }}
      />
    </MemoryRouter>,
  );

  expect(screen.getByRole("heading", { name: "Неизвестная ошибка проверки" })).toBeVisible();
  expect(screen.getByText("corr-unknown-42")).toBeVisible();
  expect(screen.queryByText("private detail")).not.toBeInTheDocument();
});
