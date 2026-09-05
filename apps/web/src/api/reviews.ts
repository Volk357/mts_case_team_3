import { requestJson } from "@/api/client";

export type ReviewStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface ReviewState {
  review_id: string;
  document_id: string;
  review_pack_id: string;
  status: ReviewStatus;
  stage: "waiting" | "analysis" | "result_ready" | "finished";
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  poll_after_ms: number | null;
  error: { code: string; message: string; retriable: boolean } | null;
}

export interface ReviewFinding {
  finding_id: string;
  ordinal: number;
  defect_id: string;
  severity: "critical" | "high" | "medium" | "low";
  confidence: number;
  location: {
    page: number | null;
    section_path: string[];
    block_id: string;
    table?: string | null;
    row?: number | string | null;
    column?: number | string | null;
    bbox?: Record<string, unknown> | null;
  };
  quote: string;
  problem: string;
  clarification: string;
  /**
   * Каким слоем найдено. `null` — слой неизвестен (ядро назвало проверку
   * именем, которого API не знает); интерфейс тогда ничего не пишет.
   * Сырых имён внутренних проверок здесь нет и быть не должно.
   */
  detection_layer: "rule" | "model" | "mixed" | null;
}

export interface ReviewFindings {
  review_id: string;
  items: ReviewFinding[];
  total: number;
}

/** Строка истории проверок: имя файла нужно, чтобы узнать свою проверку. */
export interface ReviewListItem {
  review_id: string;
  document_id: string;
  document_filename: string;
  status: ReviewStatus;
  queued_at: string;
  finished_at: string | null;
  findings_count: number;
}

export interface ReviewList {
  items: ReviewListItem[];
  total: number;
}

export function getReviews(signal?: AbortSignal) {
  return requestJson<ReviewList>("/api/reviews", { signal });
}

export function createReview(
  documentId: string,
  reviewPackId: string,
  idempotencyKey: string,
  signal?: AbortSignal,
) {
  return requestJson<ReviewState>("/api/reviews", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ document_id: documentId, review_pack_id: reviewPackId }),
    signal,
  });
}

export function getReview(reviewId: string, signal?: AbortSignal) {
  return requestJson<ReviewState>(`/api/reviews/${encodeURIComponent(reviewId)}`, { signal });
}

export function getReviewFindings(reviewId: string, signal?: AbortSignal) {
  return requestJson<ReviewFindings>(
    `/api/reviews/${encodeURIComponent(reviewId)}/findings`,
    { signal },
  );
}
