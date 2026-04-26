import { test, expect } from "@playwright/test";

test.use({ baseURL: "http://localhost:8101" });

test("session token badge appears in status bar after a simple response", async ({ page }) => {
  await page.goto("/");

  const input = page.locator("textarea").first();
  await expect(input).toBeVisible({ timeout: 10_000 });

  // No usage badge before any message
  await expect(page.locator("span.font-mono", { hasText: /↑/ })).not.toBeVisible();

  await input.fill("Say hello in one sentence.");
  await input.press("Enter");

  // Session badge in the status bar should appear after streaming completes
  const sessionBadge = page.locator("span.font-mono", { hasText: /↑/ }).first();
  await expect(sessionBadge).toBeVisible({ timeout: 60_000 });

  // Hover to show breakdown tooltip
  await sessionBadge.hover();
  await expect(page.locator("text=Input").first()).toBeVisible({ timeout: 3_000 });
  await expect(page.locator("text=Output").first()).toBeVisible();
  await expect(page.locator("text=Total").first()).toBeVisible();

  // Simple greeting should NOT trigger an AgentWorkBlock (no tool calls)
  await expect(page.locator("text=/Worked for/")).not.toBeVisible();

  // Switching to a new conversation resets the session badge
  await page.getByRole("button", { name: /New/i }).click();
  await expect(sessionBadge).not.toBeVisible({ timeout: 3_000 });
});

test("AgentWorkBlock appears and collapses for tool-using queries", async ({ page }) => {
  await page.goto("/");

  const input = page.locator("textarea").first();
  await expect(input).toBeVisible({ timeout: 10_000 });

  // Send a query that reliably triggers tool calls
  await input.fill("What data do we have available?");
  await input.press("Enter");

  // Work block should expand while the agent is working
  const workingLabel = page.locator("text=/Working/");
  await expect(workingLabel).toBeVisible({ timeout: 30_000 });

  // After the response completes, it auto-collapses to "Worked for Xs"
  const workedLabel = page.locator("text=/Worked for/");
  await expect(workedLabel).toBeVisible({ timeout: 60_000 });

  // Collapsed header should show tool call count
  await expect(page.locator("text=/tool call/")).toBeVisible({ timeout: 5_000 });

  // Click header to expand and see tool calls inside
  await workedLabel.click();
  // Tool call items are rendered with a wrench icon label
  await expect(page.locator("span.font-mono").filter({ hasText: /search_|list_|execute_/ }).first()).toBeVisible({ timeout: 3_000 });

  // Token counts appear in the collapsed header (right side)
  const workBlockTokens = page.locator("span.font-mono", { hasText: /↑/ }).first();
  await expect(workBlockTokens).toBeVisible({ timeout: 3_000 });
});
