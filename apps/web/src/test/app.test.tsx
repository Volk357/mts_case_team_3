import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "@/app";

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
