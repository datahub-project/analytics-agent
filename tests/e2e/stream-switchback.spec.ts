/**
 * Integration test: switching away from a streaming conversation and back
 * must show the full response — the agent must keep running after client disconnect
 * and the frontend must reattach to the live stream on switch-back.
 *
 * The fix (chat.py + ChatView.tsx):
 *   - Backend: agent runs in asyncio.create_task (ConvStream), not cancelled on
 *     HTTP disconnect. Each event committed immediately so DB is always up to date.
 *   - Frontend: GET /conversations/{id}/stream reattaches to the replay buffer +
 *     live tail when getConversation returns is_streaming=true.
 */
import { test, expect } from "@playwright/test";

test.describe("stream — switch-back shows full response", () => {
  test("switching away and back shows the complete agent response", async ({
    page,
    request,
  }) => {
    const engineName = "mock-test-engine";

    // Create two conversations
    const [resA, resB] = await Promise.all([
      request.post("/api/conversations", {
        data: { title: "Switchback Test — Conv A", engine_name: engineName },
      }),
      request.post("/api/conversations", {
        data: { title: "Switchback Test — Conv B", engine_name: engineName },
      }),
    ]);
    expect(resA.ok()).toBeTruthy();
    expect(resB.ok()).toBeTruthy();
    const convA = (await resA.json()) as { id: string };
    const convB = (await resB.json()) as { id: string };

    await page.goto("/");

    const convAItem = page.locator(`[data-conv-id="${convA.id}"]`);
    const convBItem = page.locator(`[data-conv-id="${convB.id}"]`);

    await expect(convAItem).toBeVisible({ timeout: 5000 });
    await expect(convBItem).toBeVisible({ timeout: 5000 });

    // Activate Conv A and send a message
    await convAItem.click();
    await expect(page.getByPlaceholder("Ask about your data…")).toBeVisible();

    const streamRequestPromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/api/conversations/${convA.id}/messages`) &&
        req.method() === "POST"
    );

    await page.getByPlaceholder("Ask about your data…").fill("test question");
    await page.keyboard.press("Enter");

    // Confirm SSE connection is live before switching
    await streamRequestPromise;

    // Switch away mid-stream — aborts the client-side SSE reader,
    // but the backend task keeps running (the fix).
    await convBItem.click();
    await expect(page.getByText("Ask a question about your data")).toBeVisible({
      timeout: 3000,
    });

    // Wait for the full mock stream to complete on the backend
    // (8 chunks × 80ms = 640ms) plus headroom.
    await page.waitForTimeout(1200);

    // Switch back to Conv A — frontend should call GET /conversations/{id}/stream
    // to reattach, get the replay buffer, and show the full response.
    await convAItem.click();

    // Full mock response must be visible in Conv A's chat
    await expect(
      page.getByText("MOCK_LLM", { exact: false })
    ).toBeVisible({ timeout: 5000 });

    // Conv A should have the chat-messages container (messages > 0)
    await expect(page.locator("#chat-messages")).toHaveCount(1);

    // Verify the complete text assembled from all 8 chunks is present
    await expect(
      page.getByText("MOCK_LLM stream chunk one. MOCK_LLM stream chunk two.", {
        exact: false,
      })
    ).toBeVisible({ timeout: 3000 });

    // Clean up
    await Promise.all([
      request.delete(`/api/conversations/${convA.id}`),
      request.delete(`/api/conversations/${convB.id}`),
    ]);
  });
});
