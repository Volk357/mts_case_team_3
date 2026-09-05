import { render, screen, within } from "@testing-library/react";

import { ArchitecturePage } from "@/pages/architecture-page";

it("shows the implemented platform flow and separates it from roadmap", () => {
  render(<ArchitecturePage />);

  expect(
    screen.getByRole("heading", { name: "Одно приложение для разных стандартов документации" }),
  ).toBeInTheDocument();
  for (const label of [
    "Company Inputs",
    "Review Pack",
    "Analysis Core",
    "Product Application",
    "On-premise Model Gateway",
    "Feedback Loop",
  ]) {
    expect(screen.getByText(label)).toBeInTheDocument();
  }

  const flow = screen.getByRole("region", { name: "Поток данных платформы" });
  expect(within(flow).getAllByText("Реализовано")).toHaveLength(6);
  expect(within(flow).queryByText("Roadmap")).not.toBeInTheDocument();

  const roadmap = screen.getByRole("region", { name: "Следующие шаги платформы" });
  expect(within(roadmap).getAllByText("Roadmap")).toHaveLength(3);
  expect(within(roadmap).queryByText("Реализовано")).not.toBeInTheDocument();
});
