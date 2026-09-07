import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { setToken } from "@/auth/session";
import { ReviewPackEditorPage } from "@/pages/review-pack-editor-page";

/*
  Редактор правил профиля.

  Проверяется поведение страницы, а не сторонний виджет. Сам CodeMirror
  подменён простым полем: в jsdom он требует измерений, которых там нет,
  а его собственная работоспособность — не наша ответственность.
  Что НЕ покрыто этим файлом и должно проверяться руками: подсветка,
  переносы и поведение курсора в настоящем редакторе.
*/
vi.mock("@uiw/react-codemirror", () => ({
  default: ({
    value,
    onChange,
    "aria-label": label,
  }: {
    value: string;
    onChange: (next: string) => void;
    "aria-label"?: string;
  }) => (
    <textarea
      aria-label={label ?? "редактор"}
      onChange={(event) => onChange(event.target.value)}
      value={value}
    />
  ),
}));
vi.mock("@codemirror/lang-yaml", () => ({ yaml: () => [] }));

const PACK_ID = "11111111-1111-1111-1111-111111111111";

const SOURCE = {
  review_pack_id: PACK_ID,
  pack_key: "mts-net",
  version: "0.2",
  display_name: "Потоковые данные и витрины (МТС NET)",
  files: {
    template: "sections:\n  - name: Общие сведения\n",
    defects: "defects:\n  - id: NO_SCHEDULE\n",
    glossary: "terms:\n  - IMEI\n",
    policy: "ceiling: 20\nbias: recall\n",
  },
};

beforeEach(() => setToken("dGVzdDp0ZXN0"));

afterEach(() => {
  setToken(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Ответы сервера по URL: страница делает два запроса при открытии. */
function stubApi(handlers: Record<string, () => Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const key = Object.keys(handlers).find((part) => url.includes(part));
      if (!key) return Promise.resolve(new Response("{}", { status: 404 }));
      return Promise.resolve(handlers[key]());
    }),
  );
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={[`/review-packs/${PACK_ID}/edit`]}>
      <Routes>
        <Route path="/review-packs/:packId/edit" element={<ReviewPackEditorPage />} />
        <Route path="*" element={<p>другая страница</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

it("показывает файлы профиля и говорит, что правка не меняет эту версию", async () => {
  stubApi({
    "/source": () => json(SOURCE),
    "/api/review-packs": () => json({ items: [], total: 0 }),
  });

  renderEditor();

  expect(await screen.findByRole("tab", { name: /policy\.yaml/ })).toBeInTheDocument();
  for (const name of ["template.yaml", "defects.yaml", "glossary.yaml"]) {
    expect(screen.getByRole("tab", { name: new RegExp(name) })).toBeInTheDocument();
  }
  // Неизменяемость опубликованной версии — не деталь, а условие
  // воспроизводимости прошлых проверок. Человек должен прочесть это до правки.
  expect(screen.getByText(/не\s+меняет эту версию/)).toBeInTheDocument();
});

it("не даёт выпустить версию, пока ничего не изменено", async () => {
  stubApi({
    "/source": () => json(SOURCE),
    "/api/review-packs": () => json({ items: [], total: 0 }),
  });

  renderEditor();

  const button = await screen.findByRole("button", { name: "Выпустить версию" });
  expect(button).toBeDisabled();
});

it("выпускает новую версию с правкой и предложенным номером", async () => {
  const created = vi.fn();
  stubApi({
    "/source": () => json(SOURCE),
    "/versions": () => {
      created();
      return json(
        { review_pack_id: "22222222-2222-2222-2222-222222222222", pack_key: "mts-net", version: "0.3" },
        201,
      );
    },
    "/api/review-packs": () => json({ items: [], total: 0 }),
  });

  renderEditor();
  const editor = await screen.findByLabelText(/policy\.yaml/);
  await userEvent.clear(editor);
  await userEvent.type(editor, "ceiling: 12");

  // Номер предлагается следующим за текущим, но остаётся полем ввода:
  // человек создаёт то, на что будут ссылаться результаты.
  expect(screen.getByLabelText("Номер версии")).toHaveValue("0.3");

  await userEvent.click(screen.getByRole("button", { name: "Выпустить версию" }));
  await waitFor(() => expect(created).toHaveBeenCalled());
});

it("показывает причину отказа от ядра дословно", async () => {
  stubApi({
    "/source": () => json(SOURCE),
    "/versions": () =>
      json(
        {
          error: {
            code: "TEMPLATE_INVALID",
            message: "регулярное выражение не компилируется: unterminated character set",
            details: [],
          },
        },
        422,
      ),
    "/api/review-packs": () => json({ items: [], total: 0 }),
  });

  renderEditor();
  const editor = await screen.findByLabelText(/policy\.yaml/);
  await userEvent.type(editor, "x");
  await userEvent.click(screen.getByRole("button", { name: "Выпустить версию" }));

  // Своего объяснения страница не придумывает: гадать за проверяющий код
  // значило бы уводить человека не в ту строку.
  expect(
    await screen.findByText(/регулярное выражение не компилируется/),
  ).toBeInTheDocument();
  expect(screen.getByText("TEMPLATE_INVALID")).toBeInTheDocument();
});

it("сообщает понятно, если профиль не найден", async () => {
  stubApi({
    "/source": () => json({ error: { code: "REVIEW_PACK_NOT_FOUND", message: "нет", details: [] } }, 404),
    "/api/review-packs": () => json({ items: [], total: 0 }),
  });

  renderEditor();

  expect(await screen.findByText("Профиль проверки не найден.")).toBeInTheDocument();
});

it("не роняет экран, когда каталог профилей недоступен", async () => {
  stubApi({
    "/source": () => json(SOURCE),
    "/api/review-packs": () => new Response("boom", { status: 500 }),
  });

  renderEditor();

  // Название берётся из самих исходников, каталог нужен лишь для украшения.
  expect(await screen.findByRole("tab", { name: /policy\.yaml/ })).toBeInTheDocument();
  expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
});
