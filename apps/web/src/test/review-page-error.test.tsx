import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppProviders } from "@/app-providers";
import { ReviewPage } from "@/pages/review-page";

it("shows a safe unknown HTTP error with its correlation ID", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "UNKNOWN_UPSTREAM",
            message: "private upstream detail",
          },
        }),
        {
          status: 418,
          headers: {
            "Content-Type": "application/json",
            "X-Correlation-ID": "corr-http-42",
          },
        },
      ),
    ),
  );

  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/reviews/review-42"]}>
        <Routes>
          <Route path="reviews/:reviewId" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </AppProviders>,
  );

  expect(await screen.findByText("Проверьте соединение и повторите запрос.")).toBeVisible();
  expect(screen.getByText("corr-http-42")).toBeVisible();
  expect(screen.queryByText("private upstream detail")).not.toBeInTheDocument();
});
