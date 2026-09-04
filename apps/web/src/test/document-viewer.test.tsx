import { render, screen } from "@testing-library/react";

import type { DocumentResponse } from "@/api/documents";
import type { ReviewFinding } from "@/api/reviews";
import { DocumentViewer } from "@/components/document-viewer";
import { buildPdfViewerUrl, normalizeHighlightBox } from "@/lib/document-location";

const pdf: DocumentResponse = {
  document_id: "document/42",
  filename: "Требования.pdf",
  size_bytes: 1_024,
  media_type: "application/pdf",
  created_at: "2026-09-04T07:00:00Z",
};

const finding: ReviewFinding = {
  finding_id: "finding-1",
  ordinal: 1,
  defect_id: "AMBIGUOUS_LOGIC",
  severity: "high",
  confidence: 0.9,
  location: {
    page: 8,
    section_path: ["Алгоритм", "Шаг 3"],
    block_id: "block-1",
  },
  quote: "Берётся последняя запись за месяц",
  problem: "Не определён порядок",
  clarification: "Уточнить сортировку",
};

it("embeds a PDF, opens the finding page and falls back to quote search", () => {
  render(<DocumentViewer document={pdf} finding={finding} />);

  const frame = screen.getByTitle("Просмотр документа Требования.pdf");
  const source = frame.getAttribute("src") ?? "";
  const fragment = new URLSearchParams(source.split("#")[1] ?? "");
  expect(source.startsWith("/api/documents/document%2F42/content#")).toBe(true);
  expect(fragment.get("page")).toBe("8");
  expect(fragment.get("zoom")).toBe("page-width");
  expect(fragment.get("search")).toBe(`"${finding.quote}"`);
  expect(screen.getByText(/Точная координатная подсветка недоступна/)).toBeVisible();
});

it("normalizes coordinates and renders a highlight over the PDF", () => {
  const located = {
    ...finding,
    location: {
      ...finding.location,
      bbox: { x: 120, y: 210, width: 240, height: 42, page_width: 600, page_height: 840 },
    },
  };
  render(<DocumentViewer document={pdf} finding={located} />);

  const highlight = screen.getByRole("img", { name: "Область выбранного замечания" });
  expect(highlight).toHaveStyle({ left: "20%", top: "25%", width: "40%", height: "5%" });
  expect(screen.getByText("Область замечания подсвечена по координатам анализа.")).toBeVisible();
  expect(screen.getByTitle("Просмотр документа Требования.pdf").getAttribute("src")).not.toContain(
    "search=",
  );
  expect(normalizeHighlightBox(located.location.bbox)).toEqual({
    left: 20,
    top: 25,
    width: 40,
    height: 5,
  });
});

it("shows a text fallback and the original file link for DOCX", () => {
  const docx: DocumentResponse = {
    ...pdf,
    filename: "Требования.docx",
    media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };
  render(<DocumentViewer document={docx} finding={finding} />);

  expect(screen.getByRole("heading", { name: "Текстовый просмотр DOCX" })).toBeVisible();
  expect(screen.getByText(`«${finding.quote}»`)).toBeVisible();
  expect(screen.getByText(/Точная подсветка в DOCX недоступна/)).toBeVisible();
  expect(screen.getByRole("link", { name: /Открыть исходный DOCX/ })).toHaveAttribute(
    "href",
    "/api/documents/document%2F42/content",
  );
});

it("rejects incomplete or unsafe bounding boxes", () => {
  expect(normalizeHighlightBox({ x: -1, y: 2, width: 3, height: 4 })).toBeUndefined();
  expect(normalizeHighlightBox({ x: 1, y: 2, width: 0, height: 4 })).toBeUndefined();
  expect(buildPdfViewerUrl(pdf.document_id, finding)).toContain("page=8");
});
