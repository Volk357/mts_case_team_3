import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { ReviewState } from "@/api/reviews";
import { AppProviders } from "@/app-providers";
import { ReviewPage } from "@/pages/review-page";

const { getReviewMock } = vi.hoisted(() => ({
  getReviewMock: vi.fn(),
}));

vi.mock("@/api/reviews", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/reviews")>();
  return { ...original, getReview: getReviewMock };
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

beforeEach(() => getReviewMock.mockReset());

it("restores a completed review from the route and stops polling", async () => {
  getReviewMock.mockResolvedValue({
    ...baseReview,
    status: "completed",
    stage: "result_ready",
    finished_at: "2026-09-04T07:01:00Z",
    poll_after_ms: null,
  });

  renderReviewRoute();

  expect(await screen.findByText("Проверка завершена")).toBeVisible();
  expect(screen.getByText(/ID проверки:/)).toHaveTextContent("review-42");
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(getReviewMock).toHaveBeenCalledTimes(1);
  expect(getReviewMock).toHaveBeenCalledWith("review-42", expect.any(AbortSignal));
});

it("polls queued and running states until the review becomes terminal", async () => {
  getReviewMock
    .mockResolvedValueOnce(baseReview)
    .mockResolvedValueOnce({
      ...baseReview,
      status: "running",
      stage: "analysis",
      started_at: "2026-09-04T07:00:01Z",
    })
    .mockResolvedValueOnce({
      ...baseReview,
      status: "completed",
      stage: "result_ready",
      started_at: "2026-09-04T07:00:01Z",
      finished_at: "2026-09-04T07:00:20Z",
      poll_after_ms: null,
    });

  renderReviewRoute();

  expect(await screen.findByText("Проверка ожидает запуска")).toBeVisible();
  expect(await screen.findByText("Проверка завершена", {}, { timeout: 2_000 })).toBeVisible();
  await waitFor(() => expect(getReviewMock).toHaveBeenCalledTimes(3));
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(getReviewMock).toHaveBeenCalledTimes(3);
});

it("explains a long-running analysis without exposing technical stages", async () => {
  getReviewMock.mockResolvedValue({
    ...baseReview,
    status: "running",
    stage: "analysis",
    queued_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    started_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
    poll_after_ms: 30_000,
  });

  renderReviewRoute();

  expect(await screen.findByText("Идёт анализ документа")).toBeVisible();
  expect(screen.getByText(/Проверка занимает больше обычного/)).toBeVisible();
  expect(screen.queryByText(/prompt|model|pid/i)).not.toBeInTheDocument();
});
