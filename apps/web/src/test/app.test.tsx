import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "@/app";
import { AppProviders } from "@/app-providers";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => vi.unstubAllGlobals());

import { afterEach, beforeEach } from "vitest";

import { setToken } from "@/auth/session";

// С коммита 92d7095 App показывает экран входа, пока в сессии нет учётных
// данных. Тесты маршрутизации проверяют не вход — сажаем токен заранее.
beforeEach(() => setToken("dGVzdDp0ZXN0"));
afterEach(() => setToken(null));

describe("App routing", () => {
  it("renders the home page", () => {
    render(
      <AppProviders>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </AppProviders>,
    );

    expect(
      screen.getByRole("heading", {
        name: "Найдите вопросы к документу до передачи в разработку",
      }),
    ).toBeInTheDocument();
  });

  it("renders a not-found page for an unknown route", () => {
    render(
      <AppProviders>
        <MemoryRouter initialEntries={["/missing"]}>
          <App />
        </MemoryRouter>
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
  });

  it("renders the platform architecture page", () => {
    render(
      <AppProviders>
        <MemoryRouter initialEntries={["/architecture"]}>
          <App />
        </MemoryRouter>
      </AppProviders>,
    );

    expect(
      screen.getByRole("heading", {
        name: "Одно приложение для разных стандартов документации",
      }),
    ).toBeInTheDocument();
  });
});
