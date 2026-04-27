import { test, expect } from "@playwright/test";

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
});

test("AgentWorkBlock appears and collapses for tool-using queries", async ({ page }) => {
  await page.goto("/");

  const input = page.locator("textarea").first();
  await expect(input).toBeVisible({ timeout: 10_000 });

  // "data" keyword triggers the mock tool-call path in mock_llm.py
  await input.fill("What data do we have available?");
  await input.press("Enter");

  // Work block should expand while the agent is working
  const workingLabel = page.locator("text=/Working/");
  await expect(workingLabel).toBeVisible({ timeout: 30_000 });

  // After the response completes, it auto-collapses to "Worked for Xs · N tool calls"
  const workBlockHeader = page.locator("button", { hasText: /Worked for/ });
  await expect(workBlockHeader).toBeVisible({ timeout: 60_000 });

  // Collapsed header should show tool call count
  await expect(workBlockHeader).toContainText(/tool call/);

  // Token counts appear in the collapsed header (right side)
  const workBlockTokens = page.locator("span.font-mono", { hasText: /↑/ }).first();
  await expect(workBlockTokens).toBeVisible({ timeout: 3_000 });

  // Wait for the 600ms auto-collapse to fire before clicking to expand
  // (clicking while still expanded would toggle it closed instead of open)
  await expect(workBlockHeader).toHaveAttribute("aria-expanded", "false", { timeout: 2_000 });
  await workBlockHeader.click();
  await expect(page.getByText("list_datasets").first()).toBeVisible({ timeout: 5_000 });
});
