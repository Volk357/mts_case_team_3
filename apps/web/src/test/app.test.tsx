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
});
