import { requestJson } from "@/api/client";

export interface ReviewPack {
  review_pack_id: string;
  display_name: string;
  document_type: string;
  version: string;
}

export interface ReviewPackCatalog {
  items: ReviewPack[];
  total: number;
}

export function getReviewPacks(signal?: AbortSignal) {
  return requestJson<ReviewPackCatalog>("/api/review-packs", { signal });
}
