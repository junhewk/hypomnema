import { describe, it, expect } from "vitest";
import { formatPredicate } from "@/lib/predicates";
import type { Predicate } from "@/lib/types";

describe("formatPredicate", () => {
  it("formats single-word predicate", () => {
    expect(formatPredicate("contradicts")).toBe("Contradicts");
  });

  it("formats multi-word predicate", () => {
    expect(formatPredicate("provides_methodology_for")).toBe(
      "Provides methodology for",
    );
  });

  it("handles all 12 predicates without throwing", () => {
    const predicates: Predicate[] = [
      "contradicts",
      "supports",
      "extends",
      "provides_methodology_for",
      "is_example_of",
      "is_prerequisite_for",
      "generalizes",
      "specializes",
      "is_analogous_to",
      "critiques",
      "applies_to",
      "derives_from",
    ];
    for (const p of predicates) {
      expect(() => formatPredicate(p)).not.toThrow();
    }
  });

  it("capitalizes first letter only, not every word", () => {
    expect(formatPredicate("is_example_of")).toBe("Is example of");
  });
});
