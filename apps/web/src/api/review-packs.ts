import { requestJson } from "@/api/client";
import type { ReviewPackListResponse, ReviewPackResponse } from "@/api/generated";

export type ReviewPack = ReviewPackResponse;
export type ReviewPackCatalog = ReviewPackListResponse;

export function getReviewPacks(signal?: AbortSignal) {
  return requestJson<ReviewPackCatalog>("/api/review-packs", { signal });
}
