import { render, screen } from "@testing-library/react";

import type { ReviewFinding } from "@/api/reviews";
import { AppProviders } from "@/app-providers";
import { FindingCard } from "@/components/finding-card";

const finding: ReviewFinding = {
  finding_id: "finding-1",
  ordinal: 0,
  defect_id: "COMPANY_SPECIFIC_RULE_42",
  severity: "low",
  confidence: 0.82,
  location: {
    page: 4,
    section_path: ["Security requirements"],
    block_id: "paragraph-7",
  },
  quote: "Access is provided when required.",
  problem: "The approval conditions are not defined.",
  clarification: "Specify the approving role and approval criteria.",
  detection_layer: "model",
};

it("safely renders an unknown defect id without a hardcoded taxonomy", () => {
  render(
    <AppProviders>
      <FindingCard actorKey="test-actor" finding={finding} />
    </AppProviders>,
  );

  expect(screen.getByRole("heading", { name: finding.problem })).toBeInTheDocument();
  expect(screen.getByText(finding.defect_id)).toBeInTheDocument();
  expect(screen.getByText("Низкая")).toBeInTheDocument();
  expect(screen.getByText(finding.clarification)).toBeInTheDocument();
});
