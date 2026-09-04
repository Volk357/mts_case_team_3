import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { AppErrorBoundary } from "@/components/app-error-boundary";

function BrokenPage(): never {
  throw new Error("private render detail");
}

it("shows a safe recovery screen without rendering exception details", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  render(
    <AppErrorBoundary>
      <BrokenPage />
    </AppErrorBoundary>,
  );

  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Не удалось отобразить страницу" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Вернуться на главную" })).toHaveAttribute("href", "/");
  expect(screen.queryByText("private render detail")).not.toBeInTheDocument();
});
