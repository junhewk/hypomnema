import { test, expect } from "@playwright/test";

test("page loads with Hypomnema in title", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Hypomnema");
});

test("ScribbleInput textarea is visible and focusable", async ({ page }) => {
  await page.goto("/");
  const textarea = page.getByPlaceholder("What are you thinking about?");
  await expect(textarea).toBeVisible();
  await textarea.focus();
  await expect(textarea).toBeFocused();
});

test("FileDropZone is visible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Drop PDF, DOCX, or MD")).toBeVisible();
});
