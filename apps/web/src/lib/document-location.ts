import { getDocumentContentUrl } from "@/api/documents";
import type { ReviewFinding } from "@/api/reviews";

const DEFAULT_PDF_WIDTH = 595;
const DEFAULT_PDF_HEIGHT = 842;

export interface HighlightBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

function finitePositive(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : undefined;
}

export function normalizeHighlightBox(
  bbox: ReviewFinding["location"]["bbox"],
): HighlightBox | undefined {
  if (!bbox) return undefined;
  const x = typeof bbox.x === "number" && Number.isFinite(bbox.x) ? bbox.x : undefined;
  const y = typeof bbox.y === "number" && Number.isFinite(bbox.y) ? bbox.y : undefined;
  const width = finitePositive(bbox.width);
  const height = finitePositive(bbox.height);
  if (x === undefined || y === undefined || !width || !height || x < 0 || y < 0) return undefined;

  const normalized = x <= 1 && y <= 1 && width <= 1 && height <= 1;
  const pageWidth = normalized
    ? 1
    : finitePositive(bbox.page_width ?? bbox.pageWidth) ?? DEFAULT_PDF_WIDTH;
  const pageHeight = normalized
    ? 1
    : finitePositive(bbox.page_height ?? bbox.pageHeight) ?? DEFAULT_PDF_HEIGHT;
  const left = Math.min(100, (x / pageWidth) * 100);
  const top = Math.min(100, (y / pageHeight) * 100);
  return {
    left,
    top,
    width: Math.max(0, Math.min(100 - left, (width / pageWidth) * 100)),
    height: Math.max(0, Math.min(100 - top, (height / pageHeight) * 100)),
  };
}

export function buildPdfViewerUrl(documentId: string, finding?: ReviewFinding): string {
  const parameters = new URLSearchParams();
  parameters.set("page", String(finding?.location.page ?? 1));
  parameters.set("zoom", "page-width");
  if (finding?.quote && !normalizeHighlightBox(finding.location.bbox)) {
    parameters.set("search", `"${finding.quote}"`);
  }
  return `${getDocumentContentUrl(documentId)}#${parameters.toString()}`;
}
