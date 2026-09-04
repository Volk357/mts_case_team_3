import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "@/app";

import { afterEach, beforeEach } from "vitest";

import { setToken } from "@/auth/session";

// С коммита 92d7095 App показывает экран входа, пока в сессии нет учётных
// данных. Тесты маршрутизации проверяют не вход — сажаем токен заранее.
beforeEach(() => setToken("dGVzdDp0ZXN0"));
afterEach(() => setToken(null));

describe("App routing", () => {
  it("renders the home page", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: "Найдите вопросы к документу до передачи в разработку",
      }),
    ).toBeInTheDocument();
  });

  it("renders a not-found page for an unknown route", () => {
    render(
      <MemoryRouter initialEntries={["/missing"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Страница не найдена" })).toBeInTheDocument();
  });
});
