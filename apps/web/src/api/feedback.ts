import { requestJson } from "@/api/client";
import type {
  FeedbackDecision,
  FeedbackResponse,
  FeedbackUpsertRequest,
} from "@/api/generated";

export type { FeedbackDecision } from "@/api/generated";
export type FindingFeedback = FeedbackResponse;

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
