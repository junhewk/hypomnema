import { test, expect } from "@playwright/test";

const mockScoredDoc = {
  id: "doc-1",
  source_type: "scribble",
  title: "Search Result",
  text: "This is a search result.",
  mime_type: null,
  source_uri: null,
  metadata: null,
  triaged: 1,
  processed: 2,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  score: 0.85,
};

const mockEdge = {
  id: "edge-1",
  source_engram_id: "eng-1",
  target_engram_id: "eng-2",
  predicate: "supports",
  confidence: 0.9,
  source_document_id: "doc-1",
  created_at: "2026-01-01T00:00:00Z",
};

const mockEngram1 = {
  id: "eng-1",
  canonical_name: "Alpha Concept",
  concept_hash: "aaa",
  description: "First concept",
  created_at: "2026-01-01T00:00:00Z",
  edges: [],
  documents: [],
};

const mockEngram2 = {
  id: "eng-2",
  canonical_name: "Beta Concept",
  concept_hash: "bbb",
  description: "Second concept",
  created_at: "2026-01-01T00:00:00Z",
  edges: [],
  documents: [],
};

test("navigate to /search, type query, see document results", async ({
  page,
}) => {
  await page.route("**/api/search/documents?*", (route) =>
    route.fulfill({ json: [mockScoredDoc] }),
  );

  await page.goto("/search");
  await page.getByTestId("search-input").fill("test");
  await expect(page.getByRole("heading", { name: "Search Result" })).toBeVisible();
});

test("toggle to knowledge mode, see edge results", async ({ page }) => {
  await page.route("**/api/search/knowledge?*", (route) =>
    route.fulfill({ json: [mockEdge] }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngram1 }),
  );
  await page.route("**/api/engrams/eng-2", (route) =>
    route.fulfill({ json: mockEngram2 }),
  );

  await page.goto("/search");
  await page.getByTestId("mode-knowledge").click();
  await page.getByTestId("search-input").fill("test");
  await expect(page.getByTestId("knowledge-results")).toBeVisible();
});

test("URL params update with query and mode", async ({ page }) => {
  await page.route("**/api/search/documents?*", (route) =>
    route.fulfill({ json: [mockScoredDoc] }),
  );

  await page.goto("/search");
  await page.getByTestId("search-input").fill("hello");
  await expect(page).toHaveURL(/q=hello/);
  await expect(page).toHaveURL(/mode=documents/);
});
