import { test, expect } from "./fixtures";

/**
 * Tests for GenericMcpForm — the "Custom MCP Server" UI for adding arbitrary
 * MCP-backed connections. Covers the three transport tabs (stdio, SSE,
 * Streamable HTTP) introduced in issue #62.
 */
test.describe("GenericMcpForm — transport tabs", () => {
  async function openCustomMcpForm(page: Parameters<Parameters<typeof test>[1]>[0]["page"]) {
    await page.goto("/");
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Add data source" }).click();
    await page.getByText("Custom MCP Server").first().click();
  }

  test("all three transport tabs are present", async ({ page }) => {
    await openCustomMcpForm(page);
    await expect(page.getByRole("button", { name: "Local process (stdio)" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Remote server (SSE)" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Remote server (Streamable HTTP)" })).toBeVisible();
  });

  test("stdio tab shows command field", async ({ page }) => {
    await openCustomMcpForm(page);
    await page.getByRole("button", { name: "Local process (stdio)" }).click();
    await expect(page.locator('input[placeholder="npx"]')).toBeVisible();
  });

  test("SSE tab shows URL field with /sse placeholder", async ({ page }) => {
    await openCustomMcpForm(page);
    await page.getByRole("button", { name: "Remote server (SSE)" }).click();
    const urlInput = page.locator('input[placeholder*="mcp.example.com/sse"]');
    await expect(urlInput).toBeVisible();
  });

  test("Streamable HTTP tab shows URL field with /mcp placeholder", async ({ page }) => {
    await openCustomMcpForm(page);
    await page.getByRole("button", { name: "Remote server (Streamable HTTP)" }).click();
    const urlInput = page.locator('input[placeholder*="mcp.example.com/mcp"]');
    await expect(urlInput).toBeVisible();
  });

  test("saving Streamable HTTP connection posts transport=streamable_http", async ({
    page,
    request,
  }) => {
    const connName = `e2e-streamable-${Date.now()}`;

    await openCustomMcpForm(page);
    await page.getByRole("button", { name: "Remote server (Streamable HTTP)" }).click();

    await page.locator('input[placeholder*="mcp.example.com/mcp"]').fill(
      "https://mcp.example.com/mcp"
    );
    await page.locator('input[placeholder="my-mcp-server"]').fill(connName);
    await page.getByRole("button", { name: "Save" }).click();

    // Connection card should appear
    await expect(page.getByText(connName)).toBeVisible({ timeout: 5000 });

    // Verify the API stored transport=streamable_http
    const res = await request.get("/api/settings/connections");
    expect(res.ok()).toBeTruthy();
    const conns = await res.json();
    const saved = conns.find((c: { name: string }) => c.name === connName);
    expect(saved).toBeTruthy();
    const mcpCfg = saved.mcp_config ?? saved.config?.mcp_config ?? {};
    expect(mcpCfg.transport).toBe("streamable_http");
    expect(mcpCfg.url).toBe("https://mcp.example.com/mcp");

    // Cleanup
    await request.delete(`/api/settings/connections/${connName}`);
  });
});
