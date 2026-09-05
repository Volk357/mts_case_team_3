import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ReviewPage } from "@/pages/review-page";

const failedReview = {
  review_id: "review-failed",
  document_id: "document-1",
  review_pack_id: "pack-1",
  status: "failed",
  stage: "finished",
  queued_at: "2026-09-05T12:00:00.000Z",
  started_at: "2026-09-05T12:00:01.000Z",
  finished_at: "2026-09-05T12:00:02.000Z",
  poll_after_ms: null,
  error: {
    code: "MODEL_UNAVAILABLE",
    message: "Модель временно недоступна.",
    retriable: true,
  },
} as const;

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

afterEach(() => vi.unstubAllGlobals());

it("starts a retry and opens the new review page", async () => {
  const queuedRetry = {
    ...failedReview,
    review_id: "review-retry",
    status: "queued",
    stage: "waiting",
    started_at: null,
    finished_at: null,
    poll_after_ms: 2000,
    error: null,
  };
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(failedReview), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(queuedRetry), { status: 202 }))
    .mockResolvedValue(new Response(JSON.stringify(queuedRetry), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(
    <MemoryRouter initialEntries={["/reviews/review-failed"]}>
      <LocationProbe />
      <Routes>
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
      </Routes>
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: "Повторить проверку" }));

  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent("/reviews/review-retry"),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/reviews/review-failed/retry",
    expect.objectContaining({ method: "POST" }),
  );
});
