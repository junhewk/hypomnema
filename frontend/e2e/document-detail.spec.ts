import { test, expect } from "@playwright/test";

const mockDocument = {
  id: "doc-test-1",
  source_type: "scribble",
  title: "Test Document",
  text: "This is a test document body.",
  mime_type: null,
  source_uri: null,
  metadata: null,
  triaged: 1,
  processed: 2,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  engrams: [
    {
      id: "eng-1",
      canonical_name: "Test Engram",
      concept_hash: "abc123",
      description: "A test engram",
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
};

const mockEngramDetail = {
  id: "eng-1",
  canonical_name: "Test Engram",
  concept_hash: "abc123",
  description: "A test engram",
  created_at: "2026-01-01T00:00:00Z",
  edges: [],
  documents: [],
};

test("navigating to /documents/{id} shows document detail", async ({
  page,
}) => {
  await page.route("**/api/documents/doc-test-1", (route) =>
    route.fulfill({ json: mockDocument }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );

  await page.goto("/documents/doc-test-1");
  await expect(page.getByRole("heading", { name: "Test Document" })).toBeVisible();
  await expect(page.getByText("This is a test document body.")).toBeVisible();
});

test("back link navigates to /", async ({ page }) => {
  await page.route("**/api/documents/doc-test-1", (route) =>
    route.fulfill({ json: mockDocument }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );
  await page.route("**/api/documents?*", (route) =>
    route.fulfill({
      json: { items: [], total: 0, offset: 0, limit: 20 },
    }),
  );

  await page.goto("/documents/doc-test-1");
  await expect(page.getByText("← back")).toBeVisible();
  await page.getByText("← back").click();
  await expect(page).toHaveURL("/");
});

test("engram badges are visible when document has engrams", async ({
  page,
}) => {
  await page.route("**/api/documents/doc-test-1", (route) =>
    route.fulfill({ json: mockDocument }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );

  await page.goto("/documents/doc-test-1");
  await expect(page.getByText("Test Engram")).toBeVisible();
});
