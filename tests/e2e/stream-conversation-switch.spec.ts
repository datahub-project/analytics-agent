/**
 * Integration test: stream events from Conversation A must not leak into Conversation B
 * when the user switches conversations while a response is in-flight.
 *
 * The fix (ChatView.tsx): an AbortController is created per handleSend call and is
 * aborted when activeId changes in the useEffect.
 *
 * Why this test is reliable:
 *   - The backend streams real HTTP SSE chunks (via MOCK_LLM=1 in the test env)
 *     with 80ms inter-chunk delays, so the frontend's reader.read() loop is live
 *     and genuinely mid-stream when we switch conversations.
 *   - This tests the actual race condition: AbortController aborting an in-progress
 *     reader.read() call, not just a pending fetch() — which is what page.route()
 *     mocks would only cover.
 *   - Without the fix the loop keeps running after the switch and injects messages
 *     into Conversation B's Zustand messages array. With the fix the AbortError
 *     terminates the loop before any chunk can be appended to the wrong conversation.
 */
import { test, expect } from "@playwright/test";

test.describe("stream — conversation-switch isolation", () => {
  test("switching conversations mid-stream does not leak response into the new conversation", async ({
    page,
    request,
  }) => {
    // MOCK_LLM=1 is set globally in playwright.config.ts — the backend skips engine
    // resolution and LLM calls, emitting pre-configured chunks via real HTTP SSE.
    const engineName = "mock-test-engine";

    // Create two named conversations via API
    const [resA, resB] = await Promise.all([
      request.post("/api/conversations", {
        data: { title: "Stream Test — Conv A", engine_name: engineName },
      }),
      request.post("/api/conversations", {
        data: { title: "Stream Test — Conv B", engine_name: engineName },
      }),
    ]);
    expect(resA.ok()).toBeTruthy();
    expect(resB.ok()).toBeTruthy();
    const convA = (await resA.json()) as { id: string };
    const convB = (await resB.json()) as { id: string };

    await page.goto("/");

    // Target conversations by their stable IDs (added via data-conv-id in ConversationItem)
    const convAItem = page.locator(`[data-conv-id="${convA.id}"]`);
    const convBItem = page.locator(`[data-conv-id="${convB.id}"]`);

    await expect(convAItem).toBeVisible({ timeout: 5000 });
    await expect(convBItem).toBeVisible({ timeout: 5000 });

    // Activate Conversation A
    await convAItem.click();
    await expect(page.getByPlaceholder("Ask about your data…")).toBeVisible();

    // Arm a request watcher BEFORE triggering the send so we can confirm the
    // SSE request is in-flight (real HTTP connection open, chunks arriving) before
    // we switch conversations.
    const streamRequestPromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/api/conversations/${convA.id}/messages`) &&
        req.method() === "POST"
    );

    // Send — the real backend starts streaming 80ms-spaced TEXT chunks
    await page.getByPlaceholder("Ask about your data…").fill("test question");
    await page.keyboard.press("Enter");

    // Ensure the SSE connection is established before switching
    await streamRequestPromise;

    // Switch to Conversation B — triggers AbortController.abort() in ChatView's
    // useEffect([activeId]), which aborts the live reader.read() mid-stream.
    await convBItem.click();

    // Conv B is empty — the empty-state placeholder must appear
    await expect(
      page.getByText("Ask a question about your data")
    ).toBeVisible({ timeout: 3000 });

    // Wait for the full mock stream to complete (8 chunks × 80ms = 640ms) plus
    // headroom for any leaked renders to be visible if the fix were absent.
    await page.waitForTimeout(1200);

    // ── Core assertions ──────────────────────────────────────────────────────
    // 1. No MOCK_LLM text visible anywhere — it all belongs to Conv A
    await expect(page.getByText("MOCK_LLM", { exact: false })).not.toBeVisible();

    // 2. Empty state still showing — no messages were injected into Conv B
    await expect(page.getByText("Ask a question about your data")).toBeVisible();

    // 3. The #chat-messages container (rendered only when messages.length > 0) must
    //    be absent — the strongest structural signal that Conv B has no messages.
    await expect(page.locator("#chat-messages")).toHaveCount(0);

    // Clean up
    await Promise.all([
      request.delete(`/api/conversations/${convA.id}`),
      request.delete(`/api/conversations/${convB.id}`),
    ]);
  });
});
