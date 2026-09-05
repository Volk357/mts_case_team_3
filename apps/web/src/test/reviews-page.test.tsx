import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { ReviewsPage } from "@/pages/reviews-page";

/*
  Мокаем глобальный fetch, а не модуль @/api/reviews: так проверяется вся
  цепочка от запроса до разметки, и отказ сети выглядит как настоящий.
  Частичный мок модуля через importOriginal здесь давал ложное падение по
  необработанному отклонению — тот же приём, что и в health-page.test.tsx.
*/
function respondWith(items: unknown[]): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items, total: items.length }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

const item = (over: Record<string, unknown> = {}) => ({
  review_id: "11111111-1111-1111-1111-111111111111",
  document_id: "22222222-2222-2222-2222-222222222222",
  document_filename: "Витрина агрегата.docx",
  status: "completed",
  queued_at: "2026-09-05T07:23:00Z",
  finished_at: "2026-09-05T07:24:10Z",
  findings_count: 12,
  ...over,
});

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  return render(
    <MemoryRouter>
      <ReviewsPage />
    </MemoryRouter>,
  );
}

it("показывает документ, число замечаний и ведёт на проверку", async () => {
  respondWith([item()]);
  renderPage();

  // Имя файла — то, по чему человек узнаёт свою проверку в списке.
  expect(await screen.findByText("Витрина агрегата.docx")).toBeInTheDocument();
  expect(screen.getByText("12 замечаний")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Витрина агрегата\.docx/ })).toHaveAttribute(
    "href",
    "/reviews/11111111-1111-1111-1111-111111111111",
  );
});

it("склоняет число замечаний", async () => {
  respondWith([
    item({ review_id: "a", findings_count: 1 }),
    item({ review_id: "b", findings_count: 3 }),
    item({ review_id: "c", findings_count: 11 }),
  ]);
  renderPage();

  expect(await screen.findByText("1 замечание")).toBeInTheDocument();
  expect(screen.getByText("3 замечания")).toBeInTheDocument();
  // 11 — исключение: «11 замечаний», а не «11 замечание».
  expect(screen.getByText("11 замечаний")).toBeInTheDocument();
});

it("вместо числа замечаний показывает состояние незавершённой проверки", async () => {
  respondWith([item({ status: "failed", findings_count: 0 })]);
  renderPage();

  expect(await screen.findByText("Не удалась")).toBeInTheDocument();
  expect(screen.queryByText("0 замечаний")).not.toBeInTheDocument();
});

it("объясняет пустой список", async () => {
  respondWith([]);
  renderPage();

  expect(
    await screen.findByText("Проверок пока нет. Загрузите документ — он появится здесь."),
  ).toBeInTheDocument();
});

it("сообщает об ошибке загрузки списка", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection refused")));
  renderPage();

  expect(
    await screen.findByText("Не удалось загрузить список проверок. Обновите страницу."),
  ).toBeInTheDocument();
});
