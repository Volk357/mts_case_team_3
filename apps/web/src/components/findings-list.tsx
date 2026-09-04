import { useEffect, useRef, type KeyboardEvent } from "react";

import type { ReviewFinding } from "@/api/reviews";
import { FindingCard } from "@/components/finding-card";

export function FindingsList({
  findings,
  selectedFindingId,
  onSelect,
}: {
  findings: ReviewFinding[];
  selectedFindingId?: string;
  onSelect: (findingId: string) => void;
}) {
  const selectionButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const previousSelectedId = useRef(selectedFindingId);

  useEffect(() => {
    if (previousSelectedId.current === selectedFindingId) return;
    previousSelectedId.current = selectedFindingId;
    const selectedIndex = findings.findIndex(
      (finding) => finding.finding_id === selectedFindingId,
    );
    selectionButtons.current[selectedIndex]?.scrollIntoView?.({ block: "nearest" });
  }, [findings, selectedFindingId]);

  if (findings.length === 0) {
    return (
      <div className="rounded-card border border-dashed border-border bg-card p-6 text-sm text-muted-foreground">
        По выбранным фильтрам замечаний нет.
      </div>
    );
  }

  const selectedIndex = findings.findIndex((finding) => finding.finding_id === selectedFindingId);
  const tabbableIndex = selectedIndex >= 0 ? selectedIndex : 0;

  const moveSelection = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let targetIndex: number | undefined;

    switch (event.key) {
      case "ArrowDown":
      case "ArrowRight":
        targetIndex = Math.min(currentIndex + 1, findings.length - 1);
        break;
      case "ArrowUp":
      case "ArrowLeft":
        targetIndex = Math.max(currentIndex - 1, 0);
        break;
      case "Home":
        targetIndex = 0;
        break;
      case "End":
        targetIndex = findings.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    const target = findings[targetIndex];
    onSelect(target.finding_id);
    selectionButtons.current[targetIndex]?.focus();
  };

  return (
    <ol aria-label="Замечания" className="space-y-3">
      {findings.map((finding, index) => {
        const selected = finding.finding_id === selectedFindingId;
        return (
          <li key={finding.finding_id}>
            <FindingCard
              finding={finding}
              onSelect={() => onSelect(finding.finding_id)}
              onSelectionKeyDown={(event) => moveSelection(event, index)}
              selected={selected}
              selectionButtonId={`finding-selection-${finding.finding_id}`}
              selectionButtonRef={(element) => {
                selectionButtons.current[index] = element;
              }}
              selectionTabIndex={index === tabbableIndex ? 0 : -1}
            />
          </li>
        );
      })}
    </ol>
  );
}
