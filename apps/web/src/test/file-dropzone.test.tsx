import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/client";
import type { DocumentUploadResponse } from "@/api/documents";
import { FileDropzone } from "@/components/file-dropzone";
import { appConfig } from "@/config";

const { uploadDocumentMock } = vi.hoisted(() => ({
  uploadDocumentMock: vi.fn(),
}));

vi.mock("@/api/documents", () => ({
  uploadDocument: uploadDocumentMock,
}));

const pdf = (name = "Требования.pdf") =>
  new File(["%PDF-1.7\n%%EOF"], name, { type: "application/pdf" });

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("File input was not rendered");
  return input;
}

beforeEach(() => {
  uploadDocumentMock.mockReset();
});

it("shows accepted formats and selected file size", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);

  expect(screen.getByText(/PDF или DOCX/)).toBeInTheDocument();
  await user.upload(fileInput(), pdf());

  expect(screen.getByText("Требования.pdf")).toBeInTheDocument();
  expect(screen.getByText("14 Б")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Заменить файл" })).toBeEnabled();
});

it("accepts drag-and-drop and lets the user replace the selection", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);
  const dropzone = screen.getByRole("button", { name: "Область загрузки документа" });

  fireEvent.drop(dropzone, { dataTransfer: { files: [pdf("Первый.pdf")] } });
  expect(screen.getByText("Первый.pdf")).toBeInTheDocument();

  await user.upload(fileInput(), pdf("Второй.pdf"));
  expect(screen.getByText("Второй.pdf")).toBeInTheDocument();
  expect(screen.queryByText("Первый.pdf")).not.toBeInTheDocument();
});

it("opens the file picker from the keyboard", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);
  const dropzone = screen.getByRole("button", { name: "Область загрузки документа" });
  const input = fileInput();
  const click = vi.spyOn(input, "click");

  await user.tab();
  expect(dropzone).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(click).toHaveBeenCalledTimes(1);
  await user.keyboard(" ");
  expect(click).toHaveBeenCalledTimes(2);
});

it("lets the user remove a valid file before submission", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);

  await user.upload(fileInput(), pdf("Черновик.pdf"));
  await user.click(screen.getByRole("button", { name: "Убрать файл" }));

  expect(screen.queryByText("Черновик.pdf")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Загрузить документ" })).not.toBeInTheDocument();
  expect(screen.getByText("Перетащите файл сюда")).toBeVisible();
});

it("explains client-side size and format errors", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);
  const oversized = pdf("Большой.pdf");
  Object.defineProperty(oversized, "size", { value: appConfig.maxUploadSizeBytes + 1 });

  await user.upload(fileInput(), oversized);
  expect(screen.getByText(/Файл больше допустимых/)).toBeInTheDocument();

  const text = new File(["notes"], "notes.txt", { type: "text/plain" });
  fireEvent.drop(screen.getByRole("button", { name: "Область загрузки документа" }), {
    dataTransfer: { files: [text] },
  });
  expect(screen.getByText("Выберите документ в формате PDF или DOCX.")).toBeInTheDocument();
});

it("renders upload progress and a successful result", async () => {
  const user = userEvent.setup();
  let finishUpload: ((receipt: DocumentUploadResponse) => void) | undefined;
  uploadDocumentMock.mockImplementation(
    (_file: File, onProgress: (percent: number) => void) =>
      new Promise<DocumentUploadResponse>((resolve) => {
        finishUpload = resolve;
        onProgress(42);
      }),
  );
  render(<FileDropzone />);
  await user.upload(fileInput(), pdf());

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));
  expect(screen.getByRole("progressbar", { name: "Прогресс загрузки" })).toHaveAttribute(
    "aria-valuenow",
    "42",
  );
  expect(screen.getByRole("progressbar", { name: "Прогресс загрузки" })).toHaveAttribute(
    "aria-valuetext",
    "Загружено 42%",
  );
  expect(screen.getByRole("button", { name: "Область загрузки документа" })).toHaveAttribute(
    "aria-disabled",
    "true",
  );

  act(() => {
    finishUpload?.({
      document_id: "00000000-0000-0000-0000-000000000001",
      filename: "Требования.pdf",
      size_bytes: 15,
      media_type: "application/pdf",
    });
  });
  expect(await screen.findByText("Документ загружен и готов к проверке.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Заменить файл" })).toBeEnabled();
});

it("turns server failures into a clear user-facing message", async () => {
  const user = userEvent.setup();
  uploadDocumentMock.mockRejectedValue(new ApiError("payload too large", 413));
  render(<FileDropzone />);
  await user.upload(fileInput(), pdf());

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));

  expect(await screen.findByText("Файл слишком большой для загрузки.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Загрузить документ" })).toBeEnabled();
});

it("explains a security rejection and preserves its correlation ID", async () => {
  const user = userEvent.setup();
  uploadDocumentMock.mockRejectedValue(
    new ApiError("scanner detail", 422, "DOCUMENT_REJECTED", "corr-upload-42"),
  );
  render(<FileDropzone />);
  await user.upload(fileInput(), pdf());

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));

  expect(
    await screen.findByText("Файл не прошёл проверку безопасности. Выберите другой документ."),
  ).toBeVisible();
  expect(screen.getByText("corr-upload-42")).toBeVisible();
  expect(screen.queryByText("scanner detail")).not.toBeInTheDocument();
});
