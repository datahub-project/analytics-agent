const BASE = "/api";

export interface McpAppUi {
  html: string;
  csp: string | null;
  permissions: string[];
}

/**
 * Fetch the HTML for an MCP App by message ID.
 *
 * The backend serves this from the disk cache (warmed by the prefetch
 * at tool-discovery time) or falls back to a live resources/read.
 * Returns null if both cache and server are unavailable (404).
 */
export async function fetchMcpAppUi(
  conversationId: string,
  messageId: string
): Promise<McpAppUi | null> {
  const res = await fetch(
    `${BASE}/conversations/${conversationId}/mcp-app/${messageId}/ui`
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch MCP App UI: ${res.status}`);
  return res.json();
}

export interface McpToolCallResult {
  content: Array<{ type: string; text?: string; [k: string]: unknown }>;
  isError?: boolean;
}

/**
 * Phase 2: scoped MCP tool proxy.
 *
 * Called by useMcpAppBridge when the iframe sends a `tools/call` JSON-RPC
 * request. The backend validates the (connection_key, tool_name) allow-list
 * before dispatching to the originating MCP server.
 *
 * Throws on network / HTTP errors; the hook re-raises as a JSON-RPC error
 * reply to the iframe.
 */
export async function callMcpAppTool(
  conversationId: string,
  appId: string,
  toolName: string,
  args: Record<string, unknown> = {}
): Promise<McpToolCallResult> {
  const res = await fetch(
    `${BASE}/conversations/${conversationId}/mcp-app/${appId}/tool-call`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool_name: toolName, arguments: args }),
    }
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`MCP tool call failed (${res.status}): ${detail}`);
  }
  return res.json();
}
