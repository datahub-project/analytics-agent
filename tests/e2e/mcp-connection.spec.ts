import { test, expect } from "./fixtures";

test.describe("MCP connection — add connection flow", () => {
  test("Save completes fast and tools populate automatically", async ({ page, request }) => {
    // Open Settings
    await page.goto("/");
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Add context platform" }).click();
    await page.getByText("DataHub via MCP").click();

    // Fill form
    await page.locator('input[placeholder="my-connection"]').fill("e2e-mcp-test");
    await page.locator('input[placeholder*="acryl.io/integrations"]').fill("evals01.acryl.io");
    await page.keyboard.press("Tab");
    await page.locator('input[placeholder*="eyJhbGci"]').fill("mock-token");

    // Click Save and time it
    const t0 = Date.now();
    await page.getByRole("button", { name: "Save" }).click();

    // Connection card should appear within 3s (fast save)
    await expect(page.getByText("e2e-mcp-test")).toBeVisible({ timeout: 3000 });
    expect(Date.now() - t0).toBeLessThan(3000);

    // Scope assertions to the newly created connection card
    const card = page.locator("[class*='border-primary']").filter({ hasText: "e2e-mcp-test" });

    // Tools should populate within 5s (background discovery with mock)
    await expect(card.getByText("search", { exact: true })).toBeVisible({ timeout: 5000 });

    // Read/write split
    await expect(card.getByText("Read tools")).toBeVisible();
    await expect(card.getByText("get_entities", { exact: true })).toBeVisible();
    await expect(card.getByText("Write tools")).toBeVisible();
    await expect(card.getByText("add_tags", { exact: true })).toBeVisible();

    // Clean up
    const del = await request.delete("/api/settings/connections/e2e-mcp-test");
    expect(del.ok()).toBeTruthy();
  });

  test("URL auto-normalizes from bare hostname", async ({ page, request }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Add context platform" }).click();
    await page.getByText("DataHub via MCP").click();

    const urlInput = page.locator('input[placeholder*="acryl.io/integrations"]');
    await urlInput.fill("mycompany.acryl.io");
    await page.keyboard.press("Tab");  // triggers onBlur → normalizeAcrylMcpUrl

    await expect(urlInput).toHaveValue("https://mycompany.acryl.io/integrations/ai/mcp/");
  });

  test("Default label is 'DataHub over MCP (name)'", async ({ page, request }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Add context platform" }).click();
    await page.getByText("DataHub via MCP").click();

    await page.locator('input[placeholder="my-connection"]').fill("label-check");
    await page.locator('input[placeholder*="acryl.io/integrations"]').fill("evals01.acryl.io");
    await page.keyboard.press("Tab");
    await page.locator('input[placeholder*="eyJhbGci"]').fill("tok");
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByText("DataHub over MCP (label-check)")).toBeVisible({ timeout: 3000 });

    await request.delete("/api/settings/connections/label-check");
  });
});
