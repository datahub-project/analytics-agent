import type React from "react";

export type ConnectionCategory = "engine" | "context_platform";
export type ConnectionTransport = "native" | "mcp-stdio" | "mcp-sse";

export interface FieldDef {
  key: string;
  label: string;
  placeholder?: string;
  /** text = default, mono = code font, password = masked, array = dynamic list, keyvalue = key=value pairs, json = validated + pretty-printed textarea */
  type?: "text" | "mono" | "password" | "array" | "keyvalue" | "json";
  required?: boolean;
  hint?: string;
  /** Called on blur — normalise/transform the raw value before it's stored. */
  transform?: (value: string) => string;
}

export interface McpConfig {
  transport: "stdio" | "sse" | "http" | "streamable_http";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
}

export interface NewConnectionPayload {
  name: string;
  label?: string;
  /** Flat string config (field key → value). */
  config: Record<string, string>;
  /** Only present for MCP connections. */
  mcpConfig?: McpConfig;
  /** Optional async action to run after the connection is saved (e.g. open SSO browser). */
  postCreate?: (name: string) => Promise<void>;
}

export interface ConnectionPlugin {
  /** Unique frontend id, used as the API `type`. e.g. "snowflake", "snowflake-mcp", "mcp-custom-engine" */
  id: string;
  /** Logical service grouping — multiple transports can share the same serviceId. */
  serviceId: string;
  label: string;
  category: ConnectionCategory;
  transport: ConnectionTransport;
  description: string;
  icon?: React.ReactNode;
  Form: React.FC<{
    onDone: (payload: NewConnectionPayload) => void;
    onCancel: () => void;
  }>;
}
