import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { ReviewPage } from "@/pages/review-page";

/*
  Предупреждения ядра обязаны быть видны на экране результата. Без них
  частичная проверка при отказе модели выглядит как обычная, а на документе
  без находок пользователь читает «Замечаний нет» — то есть противоположное
  тому, что произошло на самом деле.
*/

function stubReview(warnings: Array<{ code: string; message: string }>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const body = String(url).includes("/findings")
        ? { review_id: "r-1", items: [], total: 0 }
        : {
            review_id: "r-1",
            document_id: "d-1",
            review_pack_id: "p-1",
            status: "completed",
            stage: "finished",
            queued_at: "2026-09-05T10:00:00Z",
            started_at: "2026-09-05T10:00:01Z",
            finished_at: "2026-09-05T10:01:00Z",
            poll_after_ms: null,
            error: null,
            warnings,
          };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reviews/r-1"]}>
      <Routes>
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

it("показывает предупреждение о неполной проверке рядом с результатом", async () => {
  stubReview([
    {
      code: "MODEL_UNAVAILABLE_PARTIAL",
      message: "Модель недоступна. Показаны только замечания правил — проверка НЕПОЛНАЯ.",
    },
  ]);
  renderPage();

  expect(
    await screen.findByText(/проверка НЕПОЛНАЯ/i),
  ).toBeInTheDocument();
  // Заголовок «Замечаний нет» без этого предупреждения читался бы как «всё хорошо».
  expect(screen.getByRole("heading", { name: "Замечаний нет" })).toBeInTheDocument();
});

it("без предупреждений ничего лишнего не рисует", async () => {
  stubReview([]);
  renderPage();

  expect(await screen.findByRole("heading", { name: "Замечаний нет" })).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
