import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("offers keyboard users a skip link to the main content", async () => {
    const user = userEvent.setup();
    render(
      <AppProviders>
        <MemoryRouter initialEntries={["/"]}>
          <App />
        </MemoryRouter>
      </AppProviders>,
    );

    await user.tab();
    const skipLink = screen.getByRole("link", { name: "Перейти к содержимому" });
    expect(skipLink).toHaveFocus();
    expect(skipLink).toHaveAttribute("href", "#main-content");
    expect(document.querySelector("main")).toHaveAttribute("id", "main-content");
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
