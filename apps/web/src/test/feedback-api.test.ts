import { putFindingFeedback } from "@/api/feedback";

it("upserts finding feedback for one local actor", async () => {
  const payload = {
    feedback_id: "feedback-1",
    finding_id: "finding/1",
    decision: "accepted",
    comment: "Useful",
    created_at: "2026-09-04T06:00:00.000Z",
    updated_at: "2026-09-04T06:00:00.000Z",
  };
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await expect(
    putFindingFeedback("finding/1", "browser-session-1", "accepted", "Useful"),
  ).resolves.toEqual(payload);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/findings/finding%2F1/feedback",
    expect.objectContaining({
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Actor-Key": "browser-session-1",
      },
    }),
  );
});
