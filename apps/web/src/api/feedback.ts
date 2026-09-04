import { requestJson } from "@/api/client";
import type {
  FeedbackDecision,
  FeedbackListResponse,
  FeedbackResponse,
  FeedbackUpsertRequest,
} from "@/api/generated";

export type { FeedbackDecision } from "@/api/generated";
export type FindingFeedback = FeedbackResponse;
export type ReviewFeedback = FeedbackListResponse;

export function getReviewFeedback(
  reviewId: string,
  actorKey: string,
  signal?: AbortSignal,
) {
  return requestJson<FeedbackListResponse>(
    `/api/reviews/${encodeURIComponent(reviewId)}/feedback`,
    {
      headers: { "X-Actor-Key": actorKey },
      signal,
    },
  );
}

export function putFindingFeedback(
  findingId: string,
  actorKey: string,
  decision: FeedbackDecision,
  comment: string | null = null,
  signal?: AbortSignal,
) {
  const body: FeedbackUpsertRequest = { decision, comment };
  return requestJson<FeedbackResponse>(
    `/api/findings/${encodeURIComponent(findingId)}/feedback`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Actor-Key": actorKey,
      },
      body: JSON.stringify(body),
      signal,
    },
  );
}
