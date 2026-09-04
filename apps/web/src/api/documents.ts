import { ApiError, parseApiError, requestJson } from "@/api/client";
import type {
  DocumentResponse,
  DocumentUploadResponse,
} from "@/api/generated";
import { appConfig } from "@/config";

export type { DocumentResponse, DocumentUploadResponse } from "@/api/generated";

export function getDocument(documentId: string, signal?: AbortSignal) {
  return requestJson<DocumentResponse>(`/api/documents/${encodeURIComponent(documentId)}`, {
    signal,
  });
}

export function getDocumentContentUrl(documentId: string): string {
  return `${appConfig.apiBaseUrl}/api/documents/${encodeURIComponent(documentId)}/content`;
}

export function uploadDocument(
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<DocumentUploadResponse> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const form = new FormData();
    form.append("document", file, file.name);
    request.open("POST", `${appConfig.apiBaseUrl}/api/documents`);
    request.setRequestHeader("Accept", "application/json");
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve(request.response as DocumentUploadResponse);
        return;
      }
      const error = parseApiError(request.response);
      reject(
        new ApiError(
          error.message ?? `API request failed with status ${request.status}`,
          request.status,
          error.code,
          request.getResponseHeader("X-Correlation-ID") ?? undefined,
        ),
      );
    });
    request.addEventListener("error", () => {
      reject(new ApiError("Не удалось подключиться к серверу", 0));
    });
    request.addEventListener("abort", () => {
      reject(new DOMException("Upload aborted", "AbortError"));
    });

    const abort = () => request.abort();
    signal?.addEventListener("abort", abort, { once: true });
    request.addEventListener("loadend", () => signal?.removeEventListener("abort", abort));
    request.send(form);
  });
}
