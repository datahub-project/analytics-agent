export interface ConnectionField {
  key: string;
  label: string;
  value: string;
  sensitive: boolean;
  placeholder: string;
  /** When non-empty, this field's value is sent under `body.secrets[secret_key]`
   *  instead of `body.config[key]` on save. */
  secret_key?: string;
}

export interface ToolToggle {
  name: string;
  label: string;
  enabled: boolean;
  description?: string;
}

export interface OAuthStatus {
  available: boolean;
  connected: boolean;
  username: string;
  expires_at: string;
  expired: boolean;
}

export interface Connection {
  name: string;
  type: string;
  label: string;
  status: "connected" | "error" | "unconfigured";
  error: string;
  fields: ConnectionField[];
  tools: ToolToggle[];
  oauth: OAuthStatus;
  source: "yaml" | "ui";
  disabled?: boolean;
}

// McpConfig lives in the plugin system — re-exported here for API consumers
export type { McpConfig } from "@/components/Settings/connections/types";
import type { McpConfig } from "@/components/Settings/connections/types";

export interface CreateConnectionBody {
  name: string;
  type: string;
  label?: string;
  config: Record<string, string>;
  /** Optional secrets; each key must appear in the engine's
   *  `QueryEngine.secret_env_vars` allow-list (e.g. `{ password: "..." }`). */
  secrets?: Record<string, string>;
  /** "engine" routes to integrations table; "context_platform" routes to context_platforms table. */
  category?: string;
  mcp_config?: McpConfig;
}

export interface SaveConnectionBody {
  config?: Record<string, string>;
  secrets?: Record<string, string>;
}

export async function createConnection(body: CreateConnectionBody): Promise<{ name: string }> {
  const res = await fetch("/api/settings/connections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to create connection");
  }
  return res.json();
}

export async function deleteConnection(name: string): Promise<void> {
  const res = await fetch(`/api/settings/connections/${name}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to delete connection");
  }
}

export interface PromptData {
  content: string;
  is_custom: boolean;
}

export interface DisplaySettings {
  app_name: string;
  logo_url: string;
}

// --- Connections ---

export async function listConnections(): Promise<Connection[]> {
  const res = await fetch("/api/settings/connections");
  if (!res.ok) throw new Error("Failed to fetch connections");
  return res.json();
}

export interface DataHubCheckResult {
  name: string;
  label: string;
  success: boolean;
  message: string;
}

export interface TestConnectionResult {
  success: boolean;
  message?: string;
  error?: string;
  checks?: DataHubCheckResult[];
}

export async function testConnection(name: string): Promise<TestConnectionResult> {
  const res = await fetch(`/api/settings/connections/${name}/test`, { method: "POST" });
  if (!res.ok) throw new Error("Test request failed");
  return res.json();
}

export async function saveConnection(
  name: string,
  body: SaveConnectionBody
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`/api/settings/connections/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      config: body.config ?? {},
      secrets: body.secrets ?? {},
    }),
  });
  if (!res.ok) throw new Error("Save failed");
  return res.json();
}

/** Split a flat `{field_key: value}` map into `{config, secrets}` using each
 *  field's `secret_key` attribute. Skips empty / masked ("•...") values. */
export function splitConnectionValues(
  fields: ConnectionField[],
  values: Record<string, string>
): SaveConnectionBody {
  const config: Record<string, string> = {};
  const secrets: Record<string, string> = {};
  for (const f of fields) {
    const v = values[f.key];
    if (!v || v.includes("•")) continue;
    if (f.secret_key) {
      secrets[f.secret_key] = v;
    } else {
      config[f.key] = v;
    }
  }
  return { config, secrets };
}

export async function saveToolToggles(
  disabledTools: string[],
  enabledMutations: string[] = [],
  disabledConnections: string[] = [],
): Promise<void> {
  const res = await fetch("/api/settings/tools", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      disabled_tools: disabledTools,
      enabled_mutations: enabledMutations,
      disabled_connections: disabledConnections,
    }),
  });
  if (!res.ok) throw new Error("Save failed");
}

export async function updateConnectionTools(
  name: string,
  disabledTools: string[],
): Promise<void> {
  const res = await fetch(`/api/settings/connections/${name}/tools`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disabled_tools: disabledTools }),
  });
  if (!res.ok) throw new Error("Failed to save tool settings");
}

export async function patchConnectionLabel(name: string, label: string): Promise<void> {
  const res = await fetch(`/api/settings/connections/${name}/label`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  if (!res.ok) throw new Error("Label update failed");
}

export interface DataHubCoverageResponse {
  covered: boolean;
  dataset_count: number;
  platform?: string;
}

export async function fetchDataHubCoverage(name: string): Promise<DataHubCoverageResponse> {
  const res = await fetch(`/api/settings/connections/${name}/datahub-coverage`);
  if (!res.ok) return { covered: false, dataset_count: 0 };
  return res.json();
}

export async function fetchDataHubCapabilities(): Promise<{ semantic_search: boolean }> {
  try {
    const res = await fetch("/api/settings/datahub/capabilities");
    if (!res.ok) return { semantic_search: false };
    return res.json();
  } catch {
    return { semantic_search: false };
  }
}

// --- Prompt ---

export async function getPrompt(): Promise<PromptData> {
  const res = await fetch("/api/settings/prompt");
  if (!res.ok) throw new Error("Failed to fetch prompt");
  return res.json();
}

export async function savePrompt(content: string): Promise<void> {
  const res = await fetch("/api/settings/prompt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error("Save failed");
}

export async function resetPrompt(): Promise<void> {
  const res = await fetch("/api/settings/prompt", { method: "DELETE" });
  if (!res.ok) throw new Error("Reset failed");
}

// --- LLM settings ---

export interface LlmSettings {
  provider: string;
  model: string;
  has_key: boolean;
}

export async function getLlmSettings(): Promise<LlmSettings> {
  const res = await fetch("/api/settings/llm");
  if (!res.ok) throw new Error("Failed to fetch LLM settings");
  return res.json();
}

export async function testLlmKey(s: {
  provider: string;
  api_key: string;
  model?: string;
}): Promise<{ ok: boolean; message: string }> {
  const res = await fetch("/api/settings/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: s.provider, api_key: s.api_key, model: s.model ?? "" }),
  });
  if (!res.ok) throw new Error("Test request failed");
  return res.json();
}

export async function saveLlmSettings(s: {
  provider: string;
  api_key: string;
  model?: string;
}): Promise<void> {
  const res = await fetch("/api/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: s.provider, api_key: s.api_key, model: s.model ?? "" }),
  });
  if (!res.ok) throw new Error("Failed to save LLM settings");
}

// --- Display ---

export async function getDisplaySettings(): Promise<DisplaySettings> {
  const res = await fetch("/api/settings/display");
  if (!res.ok) throw new Error("Failed to fetch display settings");
  return res.json();
}

export async function saveDisplaySettings(s: DisplaySettings): Promise<void> {
  const res = await fetch("/api/settings/display", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_name: s.app_name, logo_url: s.logo_url }),
  });
  if (!res.ok) throw new Error("Save failed");
}
