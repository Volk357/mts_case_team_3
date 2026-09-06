import { requestJson } from "@/api/client";

/** Один файл настройки пакета: что задаёт и лежит ли он в пакете. */
export interface ReviewPackContent {
  key: string;
  filename: string;
  description: string;
  present: boolean;
}

export interface ReviewPack {
  review_pack_id: string;
  display_name: string;
  document_type: string;
  version: string;
  contents: ReviewPackContent[];
  /** Склонность приёмки профиля; null — пакет её не объявляет. */
  policy_bias: "recall" | "precision" | "balanced" | null;
}

export interface ReviewPackCatalog {
  items: ReviewPack[];
  total: number;
}

export function getReviewPacks(signal?: AbortSignal) {
  return requestJson<ReviewPackCatalog>("/api/review-packs", { signal });
}
