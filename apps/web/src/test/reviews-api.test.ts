import { getReview } from "@/api/reviews";

const completedResult = {
  schema_version: "1.0",
  run_id: "review-42",
  status: "completed",
  document: {
    filename: "requirements.pdf",
    document_type: "requirements",
    sha256: "a".repeat(64),
  },
  engine: { version: "0.1.0" },
  review_pack: { id: "default", version: "1.0" },
  model: { name: "local-model", prompt_versions: { reviewer: "1" } },
  findings: [],
  summary: {
    total_candidates: 0,
    verified_candidates: 0,
    returned_findings: 0,
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
  },
  warnings: [],
  timings: { total_ms: 10 },
} as const;

describe("reviews API", () => {
  it("returns a generated ReviewResult contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(completedResult), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getReview("review/42");

    expect(result.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/reviews/review%2F42",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });
});
