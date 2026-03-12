import { test, expect } from "@playwright/test";

const mockPoint = {
  engram_id: "eng-1",
  canonical_name: "Alpha Concept",
  x: 1,
  y: 2,
  z: 0.5,
  cluster_id: 0,
};

const mockCluster = {
  cluster_id: 0,
  label: "Science",
  engram_count: 5,
  centroid_x: 1,
  centroid_y: 2,
  centroid_z: 0.5,
};

const mockEdge = {
  source_engram_id: "eng-1",
  target_engram_id: "eng-2",
  predicate: "supports",
  confidence: 0.8,
};

test("navigate to /viz, see canvas element", async ({ page }) => {
  await page.route("**/api/viz/projections", (route) =>
    route.fulfill({ json: [mockPoint] }),
  );
  await page.route("**/api/viz/clusters", (route) =>
    route.fulfill({ json: [mockCluster] }),
  );
  await page.route("**/api/viz/edges", (route) =>
    route.fulfill({ json: [mockEdge] }),
  );

  await page.goto("/viz");
  await expect(page.getByTestId("viz-canvas")).toBeVisible();
});

test("empty data shows empty state", async ({ page }) => {
  await page.route("**/api/viz/projections", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/clusters", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/edges", (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto("/viz");
  await expect(page.getByTestId("empty-state")).toBeVisible();
});

test("nav pills link to / and /search", async ({ page }) => {
  await page.route("**/api/viz/projections", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/clusters", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/edges", (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto("/viz");
  await expect(page.getByTestId("stream-link")).toHaveAttribute("href", "/");
  await expect(page.getByTestId("search-link")).toHaveAttribute(
    "href",
    "/search",
  );
});

test("viz pill on stream page navigates to /viz", async ({ page }) => {
  await page.route("**/api/documents?*", (route) =>
    route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 20 } }),
  );
  await page.route("**/api/viz/projections", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/clusters", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/viz/edges", (route) =>
    route.fulfill({ json: [] }),
  );

  await page.goto("/");
  await page.getByTestId("viz-link").click();
  await expect(page).toHaveURL(/\/viz/);
  await expect(page.getByTestId("viz-page")).toBeVisible();
});
