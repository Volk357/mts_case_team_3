import { render, screen } from "@testing-library/react";

import { ProgressNotice } from "@/pages/review-page";

it("явно сообщает, что долгий анализ продолжается", () => {
  render(<ProgressNotice seconds={180} stage="analysis" />);

  expect(screen.getByText(/занимает дольше обычного, но продолжается/)).toBeInTheDocument();
  expect(screen.getByText(/Прошло 180 с/)).toBeInTheDocument();
  expect(
    screen.getAllByText("Читаем документ").some((element) =>
      element.classList.contains("font-medium"),
    ),
  ).toBe(true);
});
