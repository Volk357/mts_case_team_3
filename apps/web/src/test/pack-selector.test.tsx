import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, vi } from "vitest";

import { FileDropzone } from "@/components/file-dropzone";
import { setToken } from "@/auth/session";

// Выбор профиля проверки. До 6 сентября пакет всегда брался первым из
// каталога (`items[0]`), и второй профиль был недостижим из интерфейса —
// то есть платформенность нельзя было показать на демонстрации.
beforeEach(() => setToken("dGVzdDp0ZXN0"));

afterEach(() => {
  setToken(null);
  vi.unstubAllGlobals();
});

const MTS = {
  review_pack_id: "11111111-1111-1111-1111-111111111111",
  display_name: "Потоковые данные и витрины (МТС NET)",
  document_type: "technical_specification",
  version: "0.2",
  contents: [],
  policy_bias: "recall" as const,
};

const GENERIC = {
  review_pack_id: "22222222-2222-2222-2222-222222222222",
  display_name: "Универсальная техническая спецификация",
  document_type: "technical_specification",
  version: "1.0",
  contents: [],
  policy_bias: "precision" as const,
};

function stubCatalog(items: unknown[]) {
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

function renderDropzone() {
  return render(
    <MemoryRouter>
      <FileDropzone />
    </MemoryRouter>,
  );
}

describe("Выбор профиля проверки", () => {
  it("показывает выбор, когда профилей несколько, и подписывает их политику", async () => {
    stubCatalog([MTS, GENERIC]);

    renderDropzone();

    const select = await screen.findByLabelText("Профиль проверки");
    expect(select).toBeInTheDocument();

    // Подпись переводит склонность приёмки на человеческий язык: иначе
    // выбор был бы между двумя незнакомыми названиями.
    expect(
      screen.getByRole("option", { name: /показывает больше, включая спорное/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /показывает только уверенное/ }),
    ).toBeInTheDocument();
  });

  it("не показывает выбор, когда профиль один", async () => {
    stubCatalog([MTS]);

    const { container } = renderDropzone();
    await screen.findByText(/Загрузите документ/);

    // Один профиль выбирать не из чего: лишний элемент управления
    // на главном экране — шум.
    expect(container.querySelector("#review-pack")).toBeNull();
  });

  it("не показывает выбор и не ломает экран, если каталог недоступен", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("boom", { status: 500 })),
    );

    const { container } = renderDropzone();
    await screen.findByText(/Загрузите документ/);

    // Проверка тогда пойдёт первым доступным профилем, как было раньше,
    // а сообщение об ошибке на экране загрузки было бы шумом: человек
    // каталог не запрашивал.
    expect(container.querySelector("#review-pack")).toBeNull();
    expect(screen.queryByText(/boom/)).toBeNull();
  });

  it("не подписывает профиль, если склонность незнакомая", async () => {
    stubCatalog([MTS, { ...GENERIC, policy_bias: "whatever" }]);

    renderDropzone();
    await screen.findByLabelText("Профиль проверки");

    // Лучше не сказать ничего, чем показать непонятную метку.
    const option = screen.getByRole("option", {
      name: /Универсальная техническая спецификация/,
    });
    expect(option.textContent).not.toContain("—");
  });
});
