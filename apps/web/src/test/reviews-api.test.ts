import { createReview, getReview, getReviewFindings } from "@/api/reviews";

const queuedReview = {
  review_id: "review-42",
  document_id: "document-1",
  review_pack_id: "pack-1",
  status: "queued",
  stage: "waiting",
  queued_at: "2026-09-03T12:00:00.000Z",
  started_at: null,
  finished_at: null,
  poll_after_ms: 2000,
  error: null,
} as const;

describe("reviews API", () => {
  it("creates an asynchronous review with an idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(queuedReview), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createReview("document-1", "pack-1", "submit-1");

    expect(result.stage).toBe("waiting");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reviews",
      expect.objectContaining({
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Idempotency-Key": "submit-1",
        },
      }),
    );
  });

  it("polls state and obtains findings through separate endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(queuedReview), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ review_id: "review/42", items: [], total: 0, warnings: [] }),
          {
            status: 200,
          },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await getReview("review/42");
    const result = await getReviewFindings("review/42");

    expect(result.total).toBe(0);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/reviews/review%2F42/findings",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });
});
