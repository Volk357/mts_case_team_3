import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "@/app-providers";
import { HomePage } from "@/pages/home-page";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              review_pack_id: "pack-1",
              display_name: "Техническая спецификация",
              document_type: "technical_specification",
              version: "1.0",
            },
          ],
          total: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
});

afterEach(() => vi.unstubAllGlobals());

it("requires a valid document and Review Pack before upload", async () => {
  const user = userEvent.setup();
  render(
    <AppProviders>
      <HomePage />
    </AppProviders>,
  );

  const selector = await screen.findByRole("combobox", { name: "Профиль проверки" });
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("File input was not rendered");
  await user.upload(
    input,
    new File(["%PDF-1.7\n%%EOF"], "Требования.pdf", { type: "application/pdf" }),
  );

  const upload = screen.getByRole("button", { name: "Загрузить документ" });
  expect(upload).toBeDisabled();
  expect(screen.getByText("Сначала выберите профиль проверки.")).toBeVisible();

  await user.selectOptions(selector, "pack-1");

  expect(upload).toBeEnabled();
  expect(screen.getByText("Тип документа: technical_specification")).toBeVisible();
  expect(screen.getByText("Исходный документ останется без изменений")).toBeVisible();
  expect(screen.getByText(/Решение об изменении текста всегда принимает аналитик/)).toBeVisible();
});
