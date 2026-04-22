import { test as base, expect } from "@playwright/test";

export { expect };

/** Helper: create an MCP connection via API and return its name. */
async function createMcpConnection(
  request: ReturnType<typeof base.extend>["prototype"]["request"] extends never
    ? never
    : InstanceType<typeof base>["request"],
  name: string
): Promise<void> {
  const res = await request.post("/api/settings/connections", {
    data: {
      name,
      type: "datahub-mcp",
      category: "context_platform",
      config: {},
      mcp_config: {
        transport: "http",
        url: "https://mock.example.com/mcp/",
        headers: { Authorization: "Bearer mock-token" },
      },
    },
  });
  if (!res.ok()) throw new Error(`createMcpConnection failed: ${res.status()} ${await res.text()}`);
}

/** Helper: delete a connection by name via API. */
async function deleteMcpConnection(
  request: Parameters<Parameters<typeof base.extend>[0]["connection"]>[0]["request"],
  name: string
): Promise<void> {
  await request.delete(`/api/settings/connections/${name}`);
}

/** Extended test with a `connection` fixture: creates before, deletes after. */
export const test = base.extend<{
  connectionName: string;
}>({
  connectionName: async ({ request }, use) => {
    const name = `e2e-test-${Date.now()}`;
    await createMcpConnection(request as never, name);
    await use(name);
    await deleteMcpConnection(request as never, name);
  },
});
