import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewFinding, ReviewState } from "@/api/reviews";
import { AppProviders } from "@/app-providers";
import { ReviewResults } from "@/components/review-results";

const { getDocumentMock, getReviewFindingsMock } = vi.hoisted(() => ({
  getDocumentMock: vi.fn(),
  getReviewFindingsMock: vi.fn(),
}));

vi.mock("@/api/documents", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/documents")>();
  return { ...original, getDocument: getDocumentMock };
});

vi.mock("@/api/reviews", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/reviews")>();
  return { ...original, getReviewFindings: getReviewFindingsMock };
});

const document: DocumentResponse = {
  document_id: "document-1",
  filename: "Технические требования.pdf",
  size_bytes: 12_345,
  media_type: "application/pdf",
  created_at: "2026-09-04T07:00:00Z",
};

const review: ReviewState = {
  review_id: "review-42",
  document_id: document.document_id,
  review_pack_id: "pack-1",
  status: "completed",
  stage: "result_ready",
  queued_at: "2026-09-04T07:00:00Z",
  started_at: "2026-09-04T07:00:01Z",
  finished_at: "2026-09-04T07:01:00Z",
  poll_after_ms: null,
  error: null,
};

const finding = (
  findingId: string,
  ordinal: number,
  severity: ReviewFinding["severity"],
  defectId: string,
): ReviewFinding => ({
  finding_id: findingId,
  ordinal,
  defect_id: defectId,
  severity,
  confidence: 0.9,
  location: {
    page: ordinal + 1,
    section_path: ["Требования", `Раздел ${ordinal}`],
    block_id: `block-${ordinal}`,
  },
  quote: `Цитата ${ordinal}`,
  problem: `Проблема ${ordinal}`,
  clarification: `Уточнение ${ordinal}`,
});

const findings = [
  finding("finding-1", 1, "high", "AMBIGUOUS_LOGIC"),
  finding("finding-2", 2, "medium", "MISSING_SOURCE"),
  finding("finding-3", 3, "low", "AMBIGUOUS_LOGIC"),
];

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function renderResults(initialEntry = "/reviews/review-42") {
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ReviewResults review={review} />
        <LocationProbe />
      </MemoryRouter>
    </AppProviders>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  getDocumentMock.mockReset().mockResolvedValue(document);
  getReviewFindingsMock.mockReset().mockResolvedValue({
    review_id: review.review_id,
    items: findings,
    total: findings.length,
    warnings: [],
  });
});

it("builds the result information architecture and restores selection from the URL", async () => {
  renderResults("/reviews/review-42?finding=finding-2");

  expect(
    await screen.findByRole("heading", { name: "Технические требования.pdf", level: 1 }),
  ).toBeVisible();
  expect(screen.getByText("3", { selector: "strong" })).toBeVisible();
  expect(screen.getByRole("list", { name: "Замечания" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Просмотр документа" })).toBeVisible();
  const viewerSource = screen
    .getByTitle("Просмотр документа Технические требования.pdf")
    .getAttribute("src");
  expect(new URLSearchParams(viewerSource?.split("#")[1] ?? "").get("search")).toBe(
    '"Цитата 2"',
  );
  expect(screen.getByRole("button", { name: /MISSING_SOURCE/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("filters findings and keeps the active finding in the URL", async () => {
  const user = userEvent.setup();
  renderResults();

  await screen.findByRole("heading", { name: "Технические требования.pdf" });
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-1"));

  await user.selectOptions(screen.getByLabelText("Уровень серьёзности"), "low");
  expect(screen.getByText("Показано: 1 из 3")).toBeVisible();
  expect(screen.getByRole("button", { name: /#3.*AMBIGUOUS_LOGIC/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /MISSING_SOURCE/ })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-3"));

  await user.selectOptions(screen.getByLabelText("Уровень серьёзности"), "all");
  await user.click(screen.getByRole("button", { name: /MISSING_SOURCE/ }));
  expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-2");
});

it("navigates between findings with controls and the keyboard", async () => {
  const user = userEvent.setup();
  renderResults();

  const firstFinding = await screen.findByRole("button", { name: /#1.*AMBIGUOUS_LOGIC/ });
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-1"));
  expect(screen.getByText("1 из 3")).toBeVisible();
  expect(screen.getByRole("button", { name: "Предыдущее замечание" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "Следующее замечание" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-2"));
  expect(screen.getByText("2 из 3")).toBeVisible();
  expect(screen.getByRole("button", { name: /#2.*MISSING_SOURCE/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await user.click(firstFinding);
  await user.keyboard("{ArrowDown}");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-2"));
  expect(screen.getByRole("button", { name: /#2.*MISSING_SOURCE/ })).toHaveFocus();

  await user.keyboard("{End}");
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("finding=finding-3"));
  expect(screen.getByRole("button", { name: /#3.*AMBIGUOUS_LOGIC/ })).toHaveFocus();
  expect(screen.getByRole("button", { name: "Следующее замечание" })).toBeDisabled();
});

it("restores the findings list scroll position for the review", async () => {
  const firstRender = renderResults();
  await screen.findByRole("heading", { name: "Технические требования.pdf" });
  const viewport = screen.getByLabelText("Прокручиваемый список замечаний");

  Object.defineProperty(viewport, "scrollTop", { configurable: true, value: 275, writable: true });
  fireEvent.scroll(viewport);
  expect(sessionStorage.getItem("docreview.findings-scroll.review-42")).toBe("275");

  firstRender.unmount();
  renderResults();
  await screen.findByRole("heading", { name: "Технические требования.pdf" });
  await waitFor(() =>
    expect(screen.getByLabelText("Прокручиваемый список замечаний").scrollTop).toBe(275),
  );
});

it("shows a completed empty state when the review has no findings", async () => {
  getReviewFindingsMock.mockResolvedValueOnce({
    review_id: review.review_id,
    items: [],
    total: 0,
    warnings: [],
  });

  renderResults();

  expect(await screen.findByRole("heading", { name: "Замечаний не найдено" })).toBeVisible();
  expect(screen.getByText(/Автоматическая проверка завершена без замечаний/)).toBeVisible();
  expect(screen.queryByLabelText("Уровень серьёзности")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Просмотр документа" })).toBeVisible();
});

it("handles a single finding without offering unavailable navigation", async () => {
  getReviewFindingsMock.mockResolvedValueOnce({
    review_id: review.review_id,
    items: [findings[0]],
    total: 1,
    warnings: [],
  });

  renderResults();

  expect(await screen.findByText("1 из 1")).toBeVisible();
  expect(screen.getByText("замечание")).toBeVisible();
  expect(screen.getByRole("button", { name: "Предыдущее замечание" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Следующее замечание" })).toBeDisabled();
});

it.each([12, 20])("keeps a result with %i findings in a bounded list", async (total) => {
  const manyFindings = Array.from({ length: total }, (_, index) =>
    finding(`finding-${index + 1}`, index + 1, "medium", `DEFECT_${index + 1}`),
  );
  getReviewFindingsMock.mockResolvedValueOnce({
    review_id: review.review_id,
    items: manyFindings,
    total,
    warnings: [],
  });

  renderResults();

  const list = await screen.findByRole("list", { name: "Замечания" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(total);
  expect(screen.getByLabelText("Прокручиваемый список замечаний")).toHaveClass(
    "lg:max-h-[calc(100vh-8rem)]",
    "lg:overflow-y-auto",
  );
  if (total === 20) {
    expect(screen.getByText(/Показаны первые 20 замечаний/)).toBeVisible();
  } else {
    expect(screen.queryByText(/Показаны первые 20 замечаний/)).not.toBeInTheDocument();
  }
});

it("shows partial parsing warnings and falls back to a quote for an unknown defect", async () => {
  const edgeFinding = {
    ...finding("finding-edge", 1, "high", "COMPANY_SPECIFIC_UNKNOWN_DEFECT"),
    location: { page: null, section_path: [], block_id: "block-edge" },
    future_extension: { source: "next-contract-version" },
  } as ReviewFinding;
  getReviewFindingsMock.mockResolvedValueOnce({
    review_id: review.review_id,
    items: [edgeFinding],
    total: 1,
    warnings: [
      {
        code: "PARTIAL_PARSE",
        message: "Часть таблиц не удалось распознать полностью.",
      },
    ],
  });

  renderResults();

  expect(
    await screen.findByRole("heading", { name: "Документ обработан с предупреждениями" }),
  ).toBeVisible();
  expect(screen.getByText("PARTIAL_PARSE")).toBeVisible();
  expect(screen.getByText("Часть таблиц не удалось распознать полностью.")).toBeVisible();
  expect(
    screen.getByRole("button", { name: /COMPANY_SPECIFIC_UNKNOWN_DEFECT/ }),
  ).toBeVisible();
  expect(screen.getByText("Поиск по цитате")).toBeVisible();
  expect(screen.getByText(/Номер страницы недоступен/)).toBeVisible();
});
