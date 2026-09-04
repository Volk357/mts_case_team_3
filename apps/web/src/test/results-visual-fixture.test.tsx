import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppProviders } from "@/app-providers";
import { ResultsVisualFixturePage } from "@/pages/results-visual-fixture-page";

it("provides dense reproducible result states for visual verification", () => {
  render(
    <AppProviders>
      <MemoryRouter initialEntries={["/debug/results-fixture?count=20"]}>
        <ResultsVisualFixturePage />
      </MemoryRouter>
    </AppProviders>,
  );

  expect(screen.getByText("PARTIAL_PARSE")).toBeVisible();
  expect(screen.getByText(/Показаны первые 20 замечаний/)).toBeVisible();
  expect(screen.getByText(/Для каждой записи из таблицы событий/)).toBeVisible();
  expect(within(screen.getByRole("list", { name: "Замечания" })).getAllByRole("listitem")).toHaveLength(
    20,
  );
});
