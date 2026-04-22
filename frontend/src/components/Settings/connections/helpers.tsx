import type { ConnectionCategory, ConnectionPlugin, FieldDef, NewConnectionPayload } from "./types";
import { SimpleFormShell } from "./SimpleFormShell";

// ── createSimplePlugin ────────────────────────────────────────────────────

interface SimplePluginSpec {
  id: string;
  serviceId: string;
  label: string;
  category: ConnectionCategory;
  description: string;
  icon?: React.ReactNode;
  fields: FieldDef[];
  postCreate?: (name: string) => Promise<void>;
}

export function createSimplePlugin(spec: SimplePluginSpec): ConnectionPlugin {
  return {
    id: spec.id,
    serviceId: spec.serviceId,
    label: spec.label,
    category: spec.category,
    transport: "native",
    description: spec.description,
    icon: spec.icon,
    Form: ({ onDone, onCancel }) => (
      <SimpleFormShell
        fields={spec.fields}
        onCancel={onCancel}
        onDone={async (payload) => {
          const enriched: NewConnectionPayload = {
            ...payload,
            ...(spec.postCreate ? { postCreate: spec.postCreate } : {}),
          };
          await onDone(enriched);
        }}
      />
    ),
  };
}

// ── createMcpStdioPlugin ──────────────────────────────────────────────────

interface McpStdioPluginSpec {
  id: string;
  serviceId: string;
  label: string;
  category: ConnectionCategory;
  description: string;
  icon?: React.ReactNode;
  /** Fixed command (e.g. "npx"). If omitted, user fills it in. */
  command?: string;
  /** Default args pre-populated in the UI. */
  defaultArgs?: string[];
  /** Extra fields specific to this MCP server (e.g. API keys, paths). */
  extraFields?: FieldDef[];
}

export function createMcpStdioPlugin(spec: McpStdioPluginSpec): ConnectionPlugin {
  const argsField: FieldDef = {
    key: "_args",
    label: "Arguments",
    type: "array",
    placeholder: "--arg",
    hint: "one per line",
  };
  const envField: FieldDef = {
    key: "_env",
    label: "Environment variables",
    type: "keyvalue",
    hint: "KEY=value",
  };
  const commandField: FieldDef = {
    key: "_command",
    label: "Command",
    type: "mono",
    placeholder: "npx",
    required: true,
  };

  const fields: FieldDef[] = [
    ...(spec.command ? [] : [commandField]),
    argsField,
    ...(spec.extraFields ?? []),
    envField,
  ];

  return {
    id: spec.id,
    serviceId: spec.serviceId,
    label: spec.label,
    category: spec.category,
    transport: "mcp-stdio",
    description: spec.description,
    icon: spec.icon,
    Form: ({ onDone, onCancel }) => (
      <SimpleFormShell
        fields={fields}
        onCancel={onCancel}
        onDone={async (payload) => {
          const rawArgs = payload.config["_args"] ?? "";
          const rawEnv = payload.config["_env"] ?? "";
          const args = spec.defaultArgs
            ? [...spec.defaultArgs, ...rawArgs.split("\n").filter(Boolean)]
            : rawArgs.split("\n").filter(Boolean);
          const env = Object.fromEntries(
            rawEnv
              .split("\n")
              .filter(Boolean)
              .map((line) => {
                const eq = line.indexOf("=");
                return [line.slice(0, eq), line.slice(eq + 1)];
              })
          );
          const { _args: _a, _env: _e, _command: _c, ...cleanConfig } = payload.config;
          await onDone({
            ...payload,
            config: cleanConfig,
            mcpConfig: {
              transport: "stdio",
              command: spec.command ?? (_c || ""),
              args,
              env,
            },
          });
        }}
      />
    ),
  };
}

// ── createMcpSsePlugin ────────────────────────────────────────────────────

interface McpSsePluginSpec {
  id: string;
  serviceId: string;
  label: string;
  category: ConnectionCategory;
  description: string;
  icon?: React.ReactNode;
  defaultUrl?: string;
  extraFields?: FieldDef[];
}

export function createMcpSsePlugin(spec: McpSsePluginSpec): ConnectionPlugin {
  const fields: FieldDef[] = [
    {
      key: "_url",
      label: "MCP server URL",
      type: "mono",
      placeholder: spec.defaultUrl ?? "https://mcp.example.com/sse",
      required: true,
    },
    {
      key: "_headers",
      label: "Headers",
      type: "keyvalue",
      hint: "Authorization: Bearer …",
    },
    ...(spec.extraFields ?? []),
  ];

  return {
    id: spec.id,
    serviceId: spec.serviceId,
    label: spec.label,
    category: spec.category,
    transport: "mcp-sse",
    description: spec.description,
    icon: spec.icon,
    Form: ({ onDone, onCancel }) => (
      <SimpleFormShell
        fields={fields}
        onCancel={onCancel}
        onDone={async (payload) => {
          const rawHeaders = payload.config["_headers"] ?? "";
          const headers = Object.fromEntries(
            rawHeaders
              .split("\n")
              .filter(Boolean)
              .map((line) => {
                const eq = line.indexOf("=");
                return [line.slice(0, eq), line.slice(eq + 1)];
              })
          );
          const { _url, _headers: _h, ...cleanConfig } = payload.config;
          await onDone({
            ...payload,
            config: cleanConfig,
            mcpConfig: {
              transport: "sse",
              url: _url ?? "",
              headers,
            },
          });
        }}
      />
    ),
  };
}
