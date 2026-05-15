import { SimpleFormShell } from "../SimpleFormShell";
import type { ConnectionPlugin } from "../types";

function normalizeAcrylMcpUrl(raw: string): string {
  const s = raw.trim();
  if (!s) return s;
  // Prepend scheme if missing
  const withScheme = /^https?:\/\//i.test(s) ? s : `https://${s}`;
  try {
    const { hostname, pathname } = new URL(withScheme);
    if (hostname.endsWith(".acryl.io") && !pathname.includes("/integrations/ai/mcp")) {
      return `https://${hostname}/integrations/ai/mcp/`;
    }
  } catch {
    // unparseable — return as-is
  }
  return withScheme;
}

const FIELDS = [
  {
    key: "url",
    label: "MCP server URL",
    type: "mono" as const,
    placeholder: "https://<tenant>.acryl.io/integrations/ai/mcp/",
    required: true,
    transform: normalizeAcrylMcpUrl,
  },
  {
    key: "token",
    label: "Access token",
    type: "password" as const,
    placeholder: "eyJhbGci…",
    required: true,
    hint: "Sent as Authorization: Bearer <token>",
  },
]

function DataHubMcpForm({
  onDone,
  onCancel,
}: {
  onDone: (payload: import("../types").NewConnectionPayload) => void;
  onCancel: () => void;
}) {
  return (
    <SimpleFormShell
      fields={FIELDS}
      onCancel={onCancel}
      onDone={async (payload) => {
        const { url, token, ...rest } = payload.config;
        await onDone({
          ...payload,
          config: rest,
          mcpConfig: {
            transport: "http",
            url: url ?? "",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          },
        });
      }}
    />
  );
}

export const datahubMcpPlugin: ConnectionPlugin = {
  id: "datahub-mcp",
  serviceId: "datahub",
  label: "DataHub via MCP",
  category: "context_platform",
  transport: "mcp-sse",
  description: "Connect to DataHub through its managed MCP server",
  fields: FIELDS,
  Form: DataHubMcpForm,
};
