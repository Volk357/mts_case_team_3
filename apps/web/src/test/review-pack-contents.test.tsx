import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { ReviewPackContents } from "@/components/review-pack-contents";
import { setToken } from "@/auth/session";

// Мок глобального fetch, а не частичный мок модуля: частичный мок через
// importOriginal уже давал в этом проекте ложное падение на ветке ошибки
// при корректном DOM (см. историю reviews-page).
beforeEach(() => setToken("dGVzdDp0ZXN0"));

afterEach(() => {
  setToken(null);
  vi.unstubAllGlobals();
});

function stubCatalog(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

const PACK = {
  review_pack_id: "11111111-1111-1111-1111-111111111111",
  display_name: "Потоковые данные и витрины (МТС NET)",
  document_type: "technical_specification",
  version: "0.2",
  contents: [
    {
      key: "template",
      filename: "template.yaml",
      description: "Структура документа: какие разделы обязательны",
      present: true,
    },
    {
      key: "policy",
      filename: "policy.yaml",
      description: "Политика приёмки: сколько замечаний показывать",
      present: false,
    },
  ],
};

describe("Состав Review Pack", () => {
  it("показывает файлы настройки и версию применяемого набора", async () => {
    stubCatalog({ items: [PACK], total: 1 });

    render(<ReviewPackContents />);

    expect(await screen.findByText("template.yaml")).toBeInTheDocument();
    expect(screen.getByText("policy.yaml")).toBeInTheDocument();
    expect(screen.getByText("Потоковые данные и витрины (МТС NET)")).toBeInTheDocument();
    expect(screen.getByText("0.2")).toBeInTheDocument();
  });

  it("говорит про умолчания, если файл в наборе не задан", async () => {
    stubCatalog({ items: [PACK], total: 1 });

    render(<ReviewPackContents />);

    // Отсутствующий файл не прячется: иначе человек решил бы, что политика
    // приёмки задана, хотя работают умолчания ядра.
    expect(
      await screen.findByText(/В этом наборе не задан — применяются значения по умолчанию\./),
    ).toBeInTheDocument();
  });

  it("ничего не показывает, если каталог недоступен", async () => {
    stubCatalog({ error: "boom" }, 500);

    const { container } = render(<ReviewPackContents />);

    // Блок пояснительный, человек его не запрашивал: сообщение об ошибке
    // здесь было бы шумом на главном экране.
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("ничего не показывает, если пакет не объявляет состав", async () => {
    stubCatalog({ items: [{ ...PACK, contents: [] }], total: 1 });

    const { container } = render(<ReviewPackContents />);

    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
