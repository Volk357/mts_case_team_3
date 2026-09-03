import { requestJson } from "@/api/client";
import type { ReviewResult } from "@/api/contracts";

export function getReview(reviewId: string, signal?: AbortSignal) {
  return requestJson<ReviewResult>(`/api/reviews/${encodeURIComponent(reviewId)}`, {
    signal,
  });
}
