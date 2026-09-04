import { requestJson } from "@/api/client";
import type {
  FindingResponse,
  FindingsResponse,
  ReviewCreateRequest,
  ReviewResponse,
} from "@/api/generated";

export type ReviewStatus = ReviewResponse["status"];
export type ReviewState = ReviewResponse;
export type ReviewFinding = FindingResponse;
export type ReviewFindings = FindingsResponse;

export function createReview(
  documentId: string,
  reviewPackId: string,
  idempotencyKey: string,
  signal?: AbortSignal,
) {
  const body: ReviewCreateRequest = {
    document_id: documentId,
    review_pack_id: reviewPackId,
  };
  return requestJson<ReviewState>("/api/reviews", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(body),
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
