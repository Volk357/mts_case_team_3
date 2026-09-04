import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ReviewFinding } from "@/api/reviews";
import { AppProviders } from "@/app-providers";
import { FindingCard } from "@/components/finding-card";

const { putFindingFeedbackMock } = vi.hoisted(() => ({
  putFindingFeedbackMock: vi.fn(),
}));

vi.mock("@/api/feedback", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/feedback")>();
  return { ...original, putFindingFeedback: putFindingFeedbackMock };
});

const finding: ReviewFinding = {
  finding_id: "finding-42",
  ordinal: 4,
  defect_id: "AMBIGUOUS_LOGIC",
  severity: "high",
  confidence: 0.94,
  location: {
    page: 8,
    section_path: ["Алгоритм расчёта", "Шаг 3. Определение региона"],
    block_id: "block-42",
  },
  quote: "Берётся последняя запись за месяц",
  problem: "Не определён выбор при одинаковом времени событий",
  clarification: "Уточнить дополнительное правило сортировки",
};

function renderCard(onSelect = vi.fn()) {
  render(
    <AppProviders>
      <FindingCard finding={finding} onSelect={onSelect} selected />
    </AppProviders>,
  );
  return onSelect;
}

beforeEach(() => {
  localStorage.clear();
  putFindingFeedbackMock.mockReset().mockResolvedValue({
    feedback_id: "feedback-1",
    finding_id: finding.finding_id,
    decision: "accepted",
    comment: null,
    created_at: "2026-09-04T07:00:00Z",
    updated_at: "2026-09-04T07:00:00Z",
  });
});

it("shows all information needed to understand and locate a finding", () => {
  renderCard();

  expect(screen.getByText("Высокое")).toBeVisible();
  expect(screen.getByText("Страница 8")).toBeVisible();
  expect(screen.getByText("Алгоритм расчёта")).toBeVisible();
  expect(screen.getByText("Шаг 3. Определение региона")).toBeVisible();
  expect(screen.getByText("«Берётся последняя запись за месяц»")).toBeVisible();
  expect(screen.getByText("Возможная проблема")).toBeVisible();
  expect(screen.getByText(finding.problem)).toBeVisible();
  expect(screen.getByText("Что требуется уточнить")).toBeVisible();
  expect(screen.getByText(finding.clarification)).toBeVisible();
  expect(screen.queryByRole("button", { name: /переписать|исправить автоматически/i })).not.toBeInTheDocument();
});

it("saves analyst feedback without changing the selected finding", async () => {
  const user = userEvent.setup();
  const onSelect = renderCard();

  await user.click(screen.getByRole("button", { name: "Полезно" }));

  expect(await screen.findByText("Оценка сохранена.")).toBeVisible();
  expect(putFindingFeedbackMock).toHaveBeenCalledWith(
    finding.finding_id,
    expect.stringMatching(/^web-analyst-/),
    "accepted",
  );
  expect(screen.getByRole("button", { name: "Полезно" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(onSelect).not.toHaveBeenCalled();
});

it("lets the analyst select the card independently from feedback", async () => {
  const user = userEvent.setup();
  const onSelect = renderCard();

  await user.click(screen.getByRole("button", { name: /AMBIGUOUS_LOGIC/ }));

  expect(onSelect).toHaveBeenCalledTimes(1);
});
