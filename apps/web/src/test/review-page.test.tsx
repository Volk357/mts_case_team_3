import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewState } from "@/api/reviews";
import { AppProviders } from "@/app-providers";
import { ReviewPage } from "@/pages/review-page";

const { getDocumentMock, getReviewFindingsMock, getReviewWithMetadataMock } = vi.hoisted(() => ({
  getDocumentMock: vi.fn(),
  getReviewFindingsMock: vi.fn(),
  getReviewWithMetadataMock: vi.fn(),
}));

vi.mock("@/api/documents", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/documents")>();
  return { ...original, getDocument: getDocumentMock };
});

vi.mock("@/api/reviews", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/reviews")>();
  return {
    ...original,
    getReviewFindings: getReviewFindingsMock,
    getReviewWithMetadata: getReviewWithMetadataMock,
  };
});

const baseReview: ReviewState = {
  review_id: "review-42",
  document_id: "document-1",
  review_pack_id: "pack-1",
  status: "queued",
  stage: "waiting",
  queued_at: "2026-09-04T07:00:00Z",
  started_at: null,
  finished_at: null,
  poll_after_ms: 10,
  error: null,
};

function renderReviewRoute() {
  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/reviews/review-42"]}>
        <Routes>
          <Route path="reviews/:reviewId" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </AppProviders>,
  );
}

const response = (data: ReviewState, correlationId = "request-review-42") => ({
  data,
  correlationId,
});

const document: DocumentResponse = {
  document_id: "document-1",
  filename: "Требования.pdf",
  size_bytes: 1_024,
  media_type: "application/pdf",
  created_at: "2026-09-04T07:00:00Z",
};

beforeEach(() => {
  getReviewWithMetadataMock.mockReset();
  getDocumentMock.mockReset().mockResolvedValue(document);
  getReviewFindingsMock.mockReset().mockResolvedValue({
    review_id: "review-42",
    items: [],
    total: 0,
  });
});

it("restores a completed review from the route and stops polling", async () => {
  getReviewWithMetadataMock.mockResolvedValue(
    response({
      ...baseReview,
      status: "completed",
      stage: "result_ready",
      finished_at: "2026-09-04T07:01:00Z",
      poll_after_ms: null,
    }),
  );

  renderReviewRoute();

  expect(await screen.findByRole("heading", { name: "Требования.pdf", level: 1 })).toBeVisible();
  expect(screen.getByText(/ID проверки:/)).toHaveTextContent("review-42");
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(getReviewWithMetadataMock).toHaveBeenCalledTimes(1);
  expect(getReviewWithMetadataMock).toHaveBeenCalledWith("review-42", expect.any(AbortSignal));
});

it("polls queued and running states until the review becomes terminal", async () => {
  getReviewWithMetadataMock
    .mockResolvedValueOnce(response(baseReview))
    .mockResolvedValueOnce(response({
      ...baseReview,
      status: "running",
      stage: "analysis",
      started_at: "2026-09-04T07:00:01Z",
    }))
    .mockResolvedValueOnce(response({
      ...baseReview,
      status: "completed",
      stage: "result_ready",
      started_at: "2026-09-04T07:00:01Z",
      finished_at: "2026-09-04T07:00:20Z",
      poll_after_ms: null,
    }));

  renderReviewRoute();

  expect(await screen.findByText("Проверка ожидает запуска")).toBeVisible();
  expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("В очереди");
  expect(screen.getByText("Проверка ожидает запуска").closest("[aria-live]")).toHaveAttribute(
    "aria-busy",
    "true",
  );
  expect(
    await screen.findByRole("heading", { name: "Требования.pdf", level: 1 }, { timeout: 2_000 }),
  ).toBeVisible();
  await waitFor(() => expect(getReviewWithMetadataMock).toHaveBeenCalledTimes(3));
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(getReviewWithMetadataMock).toHaveBeenCalledTimes(3);
});

it("explains a long-running analysis without exposing technical stages", async () => {
  getReviewWithMetadataMock.mockResolvedValue(
    response({
      ...baseReview,
      status: "running",
      stage: "analysis",
      queued_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
      started_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
      poll_after_ms: 30_000,
    }),
  );

  renderReviewRoute();

  expect(await screen.findByText("Идёт анализ документа")).toBeVisible();
  expect(screen.getByText(/Проверка занимает больше обычного/)).toBeVisible();
  expect(screen.queryByText(/prompt|model|pid/i)).not.toBeInTheDocument();
});
