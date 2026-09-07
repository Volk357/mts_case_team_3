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

/** Тексты настраиваемых файлов пакета: то, что открывается в редакторе. */
export interface ReviewPackSource {
  review_pack_id: string;
  pack_key: string;
  version: string;
  display_name: string;
  /** Ключ файла → его содержимое. Приходят только применяемые ядром файлы. */
  files: Record<string, string>;
}

export function getReviewPackSource(packId: string, signal?: AbortSignal) {
  return requestJson<ReviewPackSource>(`/api/review-packs/${packId}/source`, { signal });
}

export interface ReviewPackVersion {
  review_pack_id: string;
  pack_key: string;
  version: string;
}

/** Выпустить новую версию пакета.

    Существующая версия не меняется никогда: на неё ссылаются прошлые
    проверки, и её номер входит в результат анализа. Поэтому правка —
    это всегда новая версия, а не сохранение поверх. */
export function createReviewPackVersion(
  packId: string,
  version: string,
  files: Record<string, string>,
  signal?: AbortSignal,
) {
  return requestJson<ReviewPackVersion>(`/api/review-packs/${packId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version, files }),
    signal,
  });
}
