import { act, fireEvent, render as renderComponent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/client";
import type { DocumentUploadResponse } from "@/api/documents";
import { FileDropzone } from "@/components/file-dropzone";
import { appConfig } from "@/config";

const { createReviewMock, getReviewPacksMock, uploadDocumentMock } = vi.hoisted(() => ({
  createReviewMock: vi.fn(),
  getReviewPacksMock: vi.fn(),
  uploadDocumentMock: vi.fn(),
}));

vi.mock("@/api/documents", () => ({
  uploadDocument: uploadDocumentMock,
}));
vi.mock("@/api/review-packs", () => ({
  getReviewPacks: getReviewPacksMock,
}));
vi.mock("@/api/reviews", () => ({
  createReview: createReviewMock,
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
  createReviewMock.mockReset();
  getReviewPacksMock.mockReset();
  getReviewPacksMock.mockResolvedValue({
    items: [
      {
        review_pack_id: "pack-architecture",
        company_name: "Example Company",
        display_name: "Architecture decisions",
        document_type: "Architecture decision record",
        version: "1.0",
        description: "Checks assumptions and decision consequences.",
      },
      {
        review_pack_id: "pack-security",
        company_name: "Another Company",
        display_name: "Security requirements",
        document_type: "Security specification",
        version: "2.1",
        description: "Checks access, audit and data protection requirements.",
      },
    ],
    total: 2,
  });
});

it("shows catalog metadata and lets the user choose a Review Pack", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);

  const options = await screen.findAllByRole("radio");
  expect(options).toHaveLength(2);
  expect(options[0]).toBeChecked();
  expect(screen.getByText("Example Company")).toBeInTheDocument();
  expect(screen.getByText("Architecture decision record · версия 1.0")).toBeInTheDocument();
  expect(
    screen.getByText("Checks assumptions and decision consequences."),
  ).toBeInTheDocument();
  const route = screen.getByTestId("active-review-route");
  expect(route).toHaveTextContent("Architecture decisions · 1.0");
  expect(route).toHaveTextContent("Единое ядро анализа");
  expect(route).toHaveTextContent("Приложение и ядро остаются теми же");

  await user.click(options[1]);
  expect(options[1]).toBeChecked();
  expect(options[0]).not.toBeChecked();
  expect(route).toHaveTextContent("Security requirements · 2.1");
  expect(route).toHaveTextContent("Security specification");
  expect(route).not.toHaveTextContent("Architecture decisions · 1.0");
});

it("shows accepted formats and selected file size", async () => {
  const user = userEvent.setup();
  render(<FileDropzone />);

  expect(screen.getByText(/DOCX, PDF или TXT до/)).toBeInTheDocument();
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

  // .txt теперь поддерживается, поэтому берём формат, который ядро не читает.
  const spreadsheet = new File(["sheet"], "Выгрузка.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.drop(screen.getByRole("button", { name: "Область загрузки документа" }), {
    dataTransfer: { files: [spreadsheet] },
  });
  expect(screen.getByText("Выберите документ в формате DOCX, PDF или TXT.")).toBeInTheDocument();
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

it("starts the review with the selected opaque pack id", async () => {
  const user = userEvent.setup();
  uploadDocumentMock.mockResolvedValue({
    document_id: "document-1",
    filename: "Требования.docx",
    size_bytes: 14,
    media_type: DOCX_TYPE,
  });
  createReviewMock.mockResolvedValue({
    review_id: "review-1",
    document_id: "document-1",
    review_pack_id: "pack-security",
    status: "queued",
    stage: "waiting",
    queued_at: "2026-09-05T12:00:00Z",
    started_at: null,
    finished_at: null,
    poll_after_ms: 2000,
    error: null,
    warnings: [],
  });
  render(<FileDropzone />);

  const options = await screen.findAllByRole("radio");
  await user.click(options[1]);
  await user.upload(fileInput(), docx());
  await user.click(screen.getByRole("button", { name: "Загрузить документ" }));
  await user.click(await screen.findByRole("button", { name: "Проверить документ" }));

  expect(createReviewMock).toHaveBeenCalledWith(
    "document-1",
    "pack-security",
    expect.any(String),
  );
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

it.each([
  ["Требования.pdf", "application/pdf"],
  ["Витрина.txt", "text/plain"],
  // Текстовый файл браузер может не пометить вовсе — это не повод отказать.
  ["Витрина.txt", ""],
])("принимает %s с типом «%s»", async (name, type) => {
  const user = userEvent.setup();
  render(<FileDropzone />);

  await user.upload(fileInput(), new File(["содержимое документа"], name, { type }));

  expect(screen.getByText(name)).toBeInTheDocument();
  expect(screen.queryByText(/Выберите документ/)).not.toBeInTheDocument();
});

it("отклоняет формат, который ядро не читает", () => {
  render(<FileDropzone />);
  const rtf = new File(["{\\rtf1}"], "Требования.rtf", { type: "application/rtf" });

  fireEvent.drop(screen.getByRole("button", { name: "Область загрузки документа" }), {
    dataTransfer: { files: [rtf] },
  });

  expect(screen.getByText("Выберите документ в формате DOCX, PDF или TXT.")).toBeInTheDocument();
  expect(uploadDocumentMock).not.toHaveBeenCalled();
});
