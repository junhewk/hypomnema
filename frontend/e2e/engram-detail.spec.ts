import { test, expect } from "@playwright/test";

const mockEngramDetail = {
  id: "eng-1",
  canonical_name: "Quantum Entanglement",
  concept_hash: "qe123",
  description: "Spooky action at a distance",
  created_at: "2026-01-01T00:00:00Z",
  edges: [
    {
      id: "edge-1",
      source_engram_id: "eng-1",
      target_engram_id: "eng-2",
      predicate: "supports",
      confidence: 0.85,
      source_document_id: "doc-1",
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
  documents: [],
};

const mockNeighbor = {
  id: "eng-2",
  canonical_name: "Bell Inequality",
  concept_hash: "bi456",
  description: "A theorem about quantum correlations",
  created_at: "2026-01-01T00:00:00Z",
  edges: [],
  documents: [],
};

const mockClusterDoc = {
  id: "doc-1",
  source_type: "scribble",
  title: "Cluster Document",
  text: "A document in the cluster.",
  mime_type: null,
  source_uri: null,
  metadata: null,
  triaged: 1,
  processed: 2,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

test("navigate to /engrams/{id}, see engram name and description", async ({
  page,
}) => {
  await page.route("**/api/engrams/eng-1/cluster", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );
  await page.route("**/api/engrams/eng-2", (route) =>
    route.fulfill({ json: mockNeighbor }),
  );

  await page.goto("/engrams/eng-1");
  await expect(
    page.getByRole("heading", { name: "Quantum Entanglement" }),
  ).toBeVisible();
  await expect(
    page.getByText("Spooky action at a distance"),
  ).toBeVisible();
});

test("NetworkPanel shows edges", async ({ page }) => {
  await page.route("**/api/engrams/eng-1/cluster", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );
  await page.route("**/api/engrams/eng-2", (route) =>
    route.fulfill({ json: mockNeighbor }),
  );

  await page.goto("/engrams/eng-1");
  await expect(page.getByTestId("network-panel")).toBeVisible();
  await expect(page.getByText("Bell Inequality")).toBeVisible();
});

test("cluster documents are listed", async ({ page }) => {
  await page.route("**/api/engrams/eng-1/cluster", (route) =>
    route.fulfill({ json: [mockClusterDoc] }),
  );
  await page.route("**/api/engrams/eng-1", (route) =>
    route.fulfill({ json: mockEngramDetail }),
  );
  await page.route("**/api/engrams/eng-2", (route) =>
    route.fulfill({ json: mockNeighbor }),
  );

  await page.goto("/engrams/eng-1");
  await expect(page.getByText("Cluster Document")).toBeVisible();
});
