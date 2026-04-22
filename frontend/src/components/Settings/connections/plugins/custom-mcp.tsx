import type { ConnectionPlugin } from "../types";
import { GenericMcpForm } from "../GenericMcpForm";

export const customMcpEnginePlugin: ConnectionPlugin = {
  id: "mcp-custom-engine",
  serviceId: "mcp-custom",
  label: "Custom MCP Server",
  category: "engine",
  transport: "mcp-stdio",
  description: "Connect to any MCP-compatible data source",
  Form: GenericMcpForm,
};

export const customMcpContextPlugin: ConnectionPlugin = {
  id: "mcp-custom-context",
  serviceId: "mcp-custom",
  label: "Custom MCP Server",
  category: "context_platform",
  transport: "mcp-stdio",
  description: "Connect to any MCP-compatible context platform",
  Form: GenericMcpForm,
};
