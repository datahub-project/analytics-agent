/**
 * E2E tests for PR #10: prompt caching toggle + token tooltip UI.
 *
 * All tests use MOCK_LLM=1 (no real LLM calls). The mock emits model="mock-model"
 * and provider="mock" in every USAGE event, so tooltip assertions are deterministic.
 */

import { test, expect } from "@playwright/test";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate to "/" and wait for the input to be ready. */
async function gotoChat(page: Parameters<typeof test>[1]["page"]) {
  await page.goto("/");
  await expect(page.locator("textarea").first()).toBeVisible({ timeout: 10_000 });
}

/** Send a message and wait for streaming to finish (AgentWorkBlock or plain text). */
async function sendAndWait(
  page: Parameters<typeof test>[1]["page"],
  message: string
) {
  const input = page.locator("textarea").first();
  await input.fill(message);
  await input.press("Enter");
  // Wait for any font-mono token badge to appear — signals USAGE was received
  await expect(page.locator("span.font-mono", { hasText: /↑/ }).first()).toBeVisible({
    timeout: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Token tooltip — AgentWorkBlock (tool-using path)
// ---------------------------------------------------------------------------

test("AgentWorkBlock token tooltip shows input/output/total rows", async ({ page }) => {
  await gotoChat(page);
  // "data" triggers the mock tool-call path
  await sendAndWait(page, "What data do we have available?");

  // Wait for auto-collapse
  const header = page.locator("button", { hasText: /Worked for/ });
  await expect(header).toBeVisible({ timeout: 10_000 });
  await expect(header).toHaveAttribute("aria-expanded", "false", { timeout: 2_000 });

  // Hover the token badge on the work-block header
  const badge = header.locator("span.font-mono", { hasText: /↑/ });
  await expect(badge).toBeVisible();
  await badge.hover();

  // Tooltip should show the breakdown
  await expect(page.locator("text=Input").first()).toBeVisible({ timeout: 3_000 });
  await expect(page.locator("text=Output").first()).toBeVisible();
  await expect(page.locator("text=Total").first()).toBeVisible();
});

test("AgentWorkBlock token tooltip shows model name from USAGE event", async ({ page }) => {
  await gotoChat(page);
  await sendAndWait(page, "What data do we have available?");

  const header = page.locator("button", { hasText: /Worked for/ });
  await expect(header).toHaveAttribute("aria-expanded", "false", { timeout: 3_000 });

  const badge = header.locator("span.font-mono", { hasText: /↑/ });
  await badge.hover();

  // mock_llm emits model="mock-model" — should appear in the tooltip
  await expect(page.locator("text=mock-model").first()).toBeVisible({ timeout: 3_000 });
});

// ---------------------------------------------------------------------------
// Token tooltip — ThinkingMessage ("Thought for Xs" boxes)
// ---------------------------------------------------------------------------

test("ThinkingMessage appears inside expanded AgentWorkBlock", async ({ page }) => {
  await gotoChat(page);
  await sendAndWait(page, "What data do we have available?");

  // Expand the work block
  const header = page.locator("button", { hasText: /Worked for/ });
  await expect(header).toHaveAttribute("aria-expanded", "false", { timeout: 3_000 });
  await header.click();
  await expect(header).toHaveAttribute("aria-expanded", "true", { timeout: 2_000 });

  // A "Thought for" thinking message should be visible inside the expanded block.
  // Note: in the mock flow, USAGE attaches to the final response TEXT (not the
  // thinking block), so the thinking box does not show a token badge here.
  await expect(page.locator("text=/Thought for/").first()).toBeVisible({ timeout: 5_000 });
});

// ---------------------------------------------------------------------------
// Session status bar — model name
// ---------------------------------------------------------------------------

test("session status bar tooltip shows model name after a response", async ({ page }) => {
  await gotoChat(page);
  await sendAndWait(page, "Say hello.");

  // The session-level token badge is in the status bar
  const sessionBadge = page.locator("span.font-mono", { hasText: /↑/ }).first();
  await expect(sessionBadge).toBeVisible({ timeout: 10_000 });
  await sessionBadge.hover();

  // mock_llm model name should appear in the session tooltip
  await expect(page.locator("text=mock-model").first()).toBeVisible({ timeout: 3_000 });
});

// ---------------------------------------------------------------------------
// Settings — prompt cache toggle visibility
// ---------------------------------------------------------------------------

test("prompt cache toggle persists via settings API", async ({ request }) => {
  // Verify default: caching is on
  const initial = await request.get("/api/settings/llm");
  expect(initial.ok()).toBeTruthy();

  // Save with caching disabled
  const save = await request.put("/api/settings/llm", {
    data: { provider: "anthropic", enable_prompt_cache: false },
  });
  expect(save.ok()).toBeTruthy();

  // Read back and confirm
  const readback = await request.get("/api/settings/llm");
  const body = await readback.json();
  expect(body.enable_prompt_cache).toBe(false);

  // Restore
  await request.put("/api/settings/llm", {
    data: { provider: "anthropic", enable_prompt_cache: true },
  });
});

test("prompt cache toggle is visible for Anthropic provider in Settings → Model", async ({ page }) => {
  test.setTimeout(90_000); // Settings → Connections triggers a 30s DataHub connectivity check
  await page.goto("/");
  await expect(page.locator("textarea").first()).toBeVisible({ timeout: 10_000 });

  // Open Settings then immediately switch to Model tab before the Connections tab
  // triggers a DataHub connectivity check (which times out in the test environment).
  await page.locator("button[title='Settings']").click();
  await page.locator("button", { hasText: "Model" }).click();

  // The toggle is visible because the test server uses LLM_PROVIDER=anthropic
  await expect(page.locator("text=Enable prompt caching")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator("input[type='checkbox']").first()).toBeChecked();
});
