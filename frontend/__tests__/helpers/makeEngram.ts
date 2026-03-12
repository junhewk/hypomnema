import type { Engram, Edge, EngramDetail, DocumentDetail } from "@/lib/types";
import { makeDoc } from "./makeDocument";

export function makeEngram(overrides: Partial<Engram> = {}): Engram {
  return {
    id: "eng-1",
    canonical_name: "Test Concept",
    concept_hash: "abc123",
    description: "A test engram",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeEdge(overrides: Partial<Edge> = {}): Edge {
  return {
    id: "edge-1",
    source_engram_id: "eng-1",
    target_engram_id: "eng-2",
    predicate: "supports",
    confidence: 0.85,
    source_document_id: "doc-1",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeEngramDetail(
  overrides: Partial<EngramDetail> & { engram?: Partial<Engram> } = {},
): EngramDetail {
  const { engram: engramOverrides, ...rest } = overrides;
  return {
    ...makeEngram(engramOverrides),
    edges: [],
    documents: [],
    ...rest,
  };
}

export function makeDocumentDetail(
  overrides: Partial<DocumentDetail> = {},
): DocumentDetail {
  return {
    ...makeDoc(),
    engrams: [],
    ...overrides,
  };
}
