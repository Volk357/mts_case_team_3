import { requestJson } from "@/api/client";

export type FeedbackDecision =
  | "accepted"
  | "false_positive"
  | "allowed_exception"
  | "already_described"
  | "not_relevant";

export interface FindingFeedback {
  feedback_id: string;
  finding_id: string;
  decision: FeedbackDecision;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export function putFindingFeedback(
  findingId: string,
  actorKey: string,
  decision: FeedbackDecision,
  comment: string | null = null,
  signal?: AbortSignal,
) {
  return requestJson<FindingFeedback>(
    `/api/findings/${encodeURIComponent(findingId)}/feedback`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Actor-Key": actorKey,
      },
      body: JSON.stringify({ decision, comment }),
      signal,
    },
  );
}
