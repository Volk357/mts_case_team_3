import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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


it("удаляет файл после подтверждения и убирает строку", async () => {
  const user = userEvent.setup();
  const calls: Array<{ url: string; method?: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method });
      if (init?.method === "DELETE") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [item()], total: 1 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
  renderPage();

  // Удаление в один клик было бы опасно: подтверждение живёт в строке.
  await user.click(await screen.findByRole("button", { name: /Удалить файл Витрина/ }));
  await user.click(screen.getByRole("button", { name: "Удалить файл" }));

  expect(
    await screen.findByText("Проверок пока нет. Загрузите документ — он появится здесь."),
  ).toBeInTheDocument();
  expect(calls.some((c) => c.method === "DELETE" && c.url.includes("/api/documents/"))).toBe(true);
});

it("не удаляет, если передумали", async () => {
  const user = userEvent.setup();
  respondWith([item()]);
  renderPage();

  await user.click(await screen.findByRole("button", { name: /Удалить файл Витрина/ }));
  await user.click(screen.getByRole("button", { name: "Отмена" }));

  expect(screen.getByText("Витрина агрегата.docx")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Удалить файл" })).not.toBeInTheDocument();
});

it("объясняет, почему файл нельзя удалить во время проверки", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        return Promise.resolve(
          new Response(
            JSON.stringify({ error: { code: "DOCUMENT_BUSY", message: "busy", details: [] } }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [item()], total: 1 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
  renderPage();

  await user.click(await screen.findByRole("button", { name: /Удалить файл Витрина/ }));
  await user.click(screen.getByRole("button", { name: "Удалить файл" }));

  expect(
    await screen.findByText("Идёт проверка этого документа — удалите после неё."),
  ).toBeInTheDocument();
  expect(screen.getByText("Витрина агрегата.docx")).toBeInTheDocument();
});


it("подтверждение раскрывается только в своей строке, даже если документ один", async () => {
  const user = userEvent.setup();
  // Один документ можно проверять несколько раз — в базе такие строки есть.
  respondWith([
    item({ review_id: "r-1" }),
    item({ review_id: "r-2", queued_at: "2026-09-04T10:00:00Z" }),
  ]);
  renderPage();

  const bins = await screen.findAllByRole("button", { name: /Удалить файл Витрина/ });
  expect(bins).toHaveLength(2);
  await user.click(bins[0]);

  // Иначе подтверждение открылось бы в обеих строках и autoFocus подрался бы
  // сам с собой.
  expect(screen.getAllByRole("button", { name: "Удалить файл" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: /Удалить файл Витрина/ })).toHaveLength(1);
});

it("Escape закрывает подтверждение", async () => {
  const user = userEvent.setup();
  respondWith([item()]);
  renderPage();

  await user.click(await screen.findByRole("button", { name: /Удалить файл Витрина/ }));
  expect(screen.getByRole("button", { name: "Удалить файл" })).toBeInTheDocument();

  await user.keyboard("{Escape}");

  expect(screen.queryByRole("button", { name: "Удалить файл" })).not.toBeInTheDocument();
});
