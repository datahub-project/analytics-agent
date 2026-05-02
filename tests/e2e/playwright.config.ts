import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

// Fresh SQLite DB per test run — guarantees isolated state
const testDbPath = join(mkdtempSync(join(tmpdir(), "analytics-agent-e2e-")), "test.db");
const TEST_PORT = 18000;

export default defineConfig({
  testDir: "./",
  testMatch: "**/*.spec.ts",
  timeout: 30_000,
  retries: 0,
  // Serial execution: all tests share one backend server so parallel runs risk
  // cross-test DB connection pool corruption (e.g. ASGI task cancellation on
  // client disconnect leaving a connection in a bad state for the next test).
  workers: 1,

  use: {
    baseURL: `http://localhost:${TEST_PORT}`,
    trace: "on-first-retry",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: {
    command: `uv run uvicorn analytics_agent.main:app --port ${TEST_PORT}`,
    url: `http://localhost:${TEST_PORT}/api/engines`,
    cwd: join(__dirname, "../.."),  // repo root so Alembic finds its config
    reuseExistingServer: false,
    env: {
      DATABASE_URL: `sqlite+aiosqlite:///${testDbPath}`,
      MOCK_MCP_TOOLS: "1",
      LLM_PROVIDER: "anthropic",
      // Provide a fake key so has_key=true and the onboarding wizard doesn't block tests
      ANTHROPIC_API_KEY: "sk-ant-test-e2e-placeholder",
      // Stream pre-configured chunks via real HTTP SSE (no actual LLM calls).
      // MOCK_LLM_DELAY_MS controls inter-chunk pacing so tests can switch mid-stream.
      MOCK_LLM: "1",
      MOCK_LLM_DELAY_MS: "80",
      // Override HOME so DataHubClient.from_env() won't find ~/.datahubenv on the
      // developer's machine and probe an unreachable DataHub instance during tests.
      HOME: testDbPath.replace(/\/[^/]+$/, ""),
    },
    timeout: 30_000,
  },
});
