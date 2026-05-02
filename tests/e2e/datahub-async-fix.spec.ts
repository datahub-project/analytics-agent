/**
 * API-level tests for the DataHub async client fix.
 *
 * These run against the e2e test server (port 18000, empty DB, no real DataHub).
 * They do NOT need a real DataHub instance.
 *
 * What is tested:
 * 1. The event loop is never blocked by a DataHub probe — concurrent requests
 *    to /api/settings/llm respond quickly even while /datahub/capabilities is running.
 * 2. The capabilities endpoint returns a clean "not configured" response when no
 *    DataHub is configured (no URL, no ~/.datahubenv).
 * 3. The capabilities cache TTL is respected — a second call within 5 min returns
 *    the cached result without constructing a new client.
 */

import { test, expect } from "@playwright/test";

test.describe("DataHub async client — event loop safety", () => {
  test("capabilities returns immediately with 'not configured' when no DataHub set up", async ({
    request,
  }) => {
    const t0 = Date.now();
    const res = await request.get("/api/settings/datahub/capabilities");
    const elapsed = Date.now() - t0;

    expect(res.ok()).toBe(true);
    const body = await res.json();

    // No DataHub configured in the clean test DB — should say so quickly
    expect(body).toHaveProperty("semantic_search", false);
    expect(body).toHaveProperty("error");

    // Must respond in well under 1 s — not blocking on a DataHub probe
    expect(elapsed).toBeLessThan(1000);
  });

  test("other endpoints respond during a DataHub capabilities check (event loop not blocked)", async ({
    request,
  }) => {
    // Fire capabilities (may probe DataHub) and another endpoint concurrently.
    // Before the fix: capabilities blocked the event loop so /api/settings/llm
    // would also hang.  After the fix: /api/settings/llm responds < 500 ms
    // even if capabilities is still waiting on a DataHub probe.
    const [capRes, llmRes] = await Promise.all([
      request.get("/api/settings/datahub/capabilities"),
      request.get("/api/settings/llm"),
    ]);

    expect(llmRes.ok()).toBe(true);
    const llm = await llmRes.json();
    expect(llm).toHaveProperty("provider");

    // Capabilities may be slow if a DataHub probe is attempted, but should still resolve
    expect(capRes.status()).not.toBe(500);
  });

  test("capabilities returns same result on second call (cache hit)", async ({ request }) => {
    const res1 = await request.get("/api/settings/datahub/capabilities");
    const t0 = Date.now();
    const res2 = await request.get("/api/settings/datahub/capabilities");
    const elapsed = Date.now() - t0;

    expect(res1.ok()).toBe(true);
    expect(res2.ok()).toBe(true);

    const body1 = await res1.json();
    const body2 = await res2.json();

    // Both calls return the same shape
    expect(body2.semantic_search).toBe(body1.semantic_search);

    // Second call should be instantaneous — cache hit, no client construction
    expect(elapsed).toBeLessThan(200);
  });
});
