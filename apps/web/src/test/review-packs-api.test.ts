import { getReviewPacks } from "@/api/review-packs";

it("loads the public Review Pack catalog without server locators", async () => {
  const payload = {
    items: [
      {
        review_pack_id: "pack-1",
        display_name: "Technical requirements",
        document_type: "technical_specification",
        version: "1.0",
      },
    ],
    total: 1,
  };
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await expect(getReviewPacks()).resolves.toEqual(payload);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/review-packs",
    expect.objectContaining({ headers: { Accept: "application/json" } }),
  );
  expect(JSON.stringify(payload)).not.toContain("locator");
});
