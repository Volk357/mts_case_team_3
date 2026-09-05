import { act, fireEvent, render as renderComponent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const docx = (name = "Требования.docx") =>
  new File(["PK\u0003\u0004 docx-body"], name, { type: DOCX_TYPE });

// FileDropzone уводит на страницу проверки через useNavigate: без роутера
// он падает ещё на рендере.
function render(ui: React.ReactElement) {
  return renderComponent(<MemoryRouter>{ui}</MemoryRouter>);
}

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

  expect(screen.getByText(/DOCX до/)).toBeInTheDocument();
  await user.upload(fileInput(), docx());

  expect(screen.getByText("Требования.docx")).toBeInTheDocument();
  expect(screen.getByText("14 Б")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Заменить файл" })).toBeEnabled();
});

it("accepts drag-and-drop and lets the user replace the selection", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);
  const dropzone = screen.getByRole("button", { name: "Область загрузки документа" });

  fireEvent.drop(dropzone, { dataTransfer: { files: [docx("Первый.docx")] } });
  expect(screen.getByText("Первый.docx")).toBeInTheDocument();

  await user.upload(fileInput(), docx("Второй.docx"));
  expect(screen.getByText("Второй.docx")).toBeInTheDocument();
  expect(screen.queryByText("Первый.docx")).not.toBeInTheDocument();
});

it("explains client-side size and format errors", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);
  const oversized = docx("Большой.docx");
  Object.defineProperty(oversized, "size", { value: appConfig.maxUploadSizeBytes + 1 });

  await user.upload(fileInput(), oversized);
  expect(screen.getByText(/Файл больше допустимых/)).toBeInTheDocument();

  const text = new File(["notes"], "notes.txt", { type: "text/plain" });
  fireEvent.drop(screen.getByRole("button", { name: "Область загрузки документа" }), {
    dataTransfer: { files: [text] },
  });
  expect(screen.getByText("Выберите документ в формате DOCX.")).toBeInTheDocument();
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
  await user.upload(fileInput(), docx());

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));
  expect(screen.getByRole("progressbar", { name: "Прогресс загрузки" })).toHaveAttribute(
    "aria-valuenow",
    "42",
  );

  act(() => {
    finishUpload?.({
      document_id: "00000000-0000-0000-0000-000000000001",
      filename: "Требования.docx",
      size_bytes: 15,
      media_type: DOCX_TYPE,
    });
  });
  expect(await screen.findByText("Документ загружен. Проверка занимает около минуты.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Заменить файл" })).toBeEnabled();
});

it("turns server failures into a clear user-facing message", async () => {
  const user = userEvent.setup();
  uploadDocumentMock.mockRejectedValue(new ApiError("payload too large", 413));
  render(<FileDropzone />);
  await user.upload(fileInput(), docx());

  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));

  expect(await screen.findByText("Файл слишком большой для загрузки.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Загрузить документ" })).toBeEnabled();
});

it("отклоняет PDF и объясняет, что делать", () => {
  render(<FileDropzone />);
  const pdf = new File(["%PDF-1.7\n%%EOF"], "Требования.pdf", { type: "application/pdf" });

  fireEvent.drop(screen.getByRole("button", { name: "Область загрузки документа" }), {
    dataTransfer: { files: [pdf] },
  });

  // Извлекать текст из PDF в закрытом контуре нечем: отказать надо сразу,
  // а не после загрузки и минуты ожидания.
  expect(screen.getByText("PDF пока не поддерживается. Сохраните документ в DOCX.")).toBeInTheDocument();
  expect(screen.queryByText("Требования.pdf")).not.toBeInTheDocument();
  expect(uploadDocumentMock).not.toHaveBeenCalled();
});
