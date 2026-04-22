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
    },
    timeout: 30_000,
  },
});
