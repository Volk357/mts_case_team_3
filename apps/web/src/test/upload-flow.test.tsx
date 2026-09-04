import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ApiError } from "@/api/client";
import { AppProviders } from "@/app-providers";
import { HomePage } from "@/pages/home-page";

const { createReviewMock, uploadDocumentMock } = vi.hoisted(() => ({
  createReviewMock: vi.fn(),
  uploadDocumentMock: vi.fn(),
}));

vi.mock("@/api/documents", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/documents")>();
  return { ...original, uploadDocument: uploadDocumentMock };
});

vi.mock("@/api/reviews", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/reviews")>();
  return { ...original, createReview: createReviewMock };
});

const documentReceipt = {
  document_id: "22222222-2222-4222-8222-222222222222",
  filename: "Требования.pdf",
  size_bytes: 14,
  media_type: "application/pdf",
};

const reviewReceipt = {
  review_id: "33333333-3333-4333-8333-333333333333",
  document_id: documentReceipt.document_id,
  review_pack_id: "pack-1",
  status: "queued",
  stage: "waiting",
  queued_at: "2026-09-04T07:00:00Z",
  started_at: null,
  finished_at: null,
  poll_after_ms: 2000,
  error: null,
};

function mockReviewPacks() {
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
}

async function prepareForm() {
  const user = userEvent.setup();
  render(
    <AppProviders>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </AppProviders>,
  );
  const selector = await screen.findByRole("combobox", { name: "Профиль проверки" });
  await user.selectOptions(selector, "pack-1");
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("File input was not rendered");
  await user.upload(
    input,
    new File(["%PDF-1.7\n%%EOF"], "Требования.pdf", { type: "application/pdf" }),
  );
  return { user, selector };
}

beforeEach(() => {
  mockReviewPacks();
  uploadDocumentMock.mockReset();
  createReviewMock.mockReset();
  uploadDocumentMock.mockImplementation(
    (_file: File, onProgress: (progress: number) => void) => {
      onProgress(55);
      return Promise.resolve(documentReceipt);
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

it("uploads the document, creates a review and clears the form", async () => {
  createReviewMock.mockResolvedValue(reviewReceipt);
  const { user, selector } = await prepareForm();

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));

  expect(await screen.findByText(/Проверка запущена/)).toBeVisible();
  expect(createReviewMock).toHaveBeenCalledWith(
    documentReceipt.document_id,
    "pack-1",
    `web-${documentReceipt.document_id}-pack-1`,
  );
  expect(selector).toHaveValue("");
  expect(screen.queryByText("Требования.pdf")).not.toBeInTheDocument();
  expect(screen.getByText("Перетащите файл сюда")).toBeVisible();
});

it("retries review creation without uploading the document twice", async () => {
  createReviewMock
    .mockRejectedValueOnce(new ApiError("Connection refused", 0))
    .mockResolvedValueOnce(reviewReceipt);
  const { user } = await prepareForm();

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));
  expect(await screen.findByText("Не удалось подключиться к серверу. Повторите запуск.")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "Повторить запуск" }));

  expect(await screen.findByText(/Проверка запущена/)).toBeVisible();
  expect(uploadDocumentMock).toHaveBeenCalledTimes(1);
  expect(createReviewMock).toHaveBeenCalledTimes(2);
});
