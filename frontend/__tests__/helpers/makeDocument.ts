import type { Document, ScoredDocument } from "@/lib/types";

export function makeDoc(overrides: Partial<Document> = {}): Document {
  return {
    id: "doc-1",
    source_type: "scribble",
    title: null,
    text: "test",
    mime_type: null,
    source_uri: null,
    metadata: null,
    triaged: 0,
    processed: 0,
    tidy_title: null,
    tidy_text: null,
    tidy_level: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeDocs(ids: string[]): Document[] {
  return ids.map((id) => makeDoc({ id }));
}

export function makeScoredDoc(overrides: Partial<ScoredDocument> = {}): ScoredDocument {
  return {
    ...makeDoc(),
    score: 0.75,
    ...overrides,
  };
}
