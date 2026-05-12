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
  /** Active non-SSO auth method — lets the frontend pre-select the correct auth tab. */
  auth_method?: "privatekey" | "password" | "pat" | "sso" | null;
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
  has_aws_keys?: boolean;
  aws_region?: string;
  enable_prompt_cache?: boolean;
  base_url?: string;
  openai_compatible_model?: string;
  has_openai_compatible_headers?: boolean;
  openai_compatible_header_keys?: string[];
}

/** Bedrock-only credential fields. All optional — leave blank to use the
 *  default AWS credential chain (env vars, ~/.aws, IAM role). */
export interface BedrockCredentials {
  aws_region?: string;
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  aws_session_token?: string;
}

export async function getLlmSettings(): Promise<LlmSettings> {
  const res = await fetch("/api/settings/llm");
  if (!res.ok) throw new Error("Failed to fetch LLM settings");
  return res.json();
}

const LLM_VERIFY_TIMEOUT_MS = 30_000;

/** Shown when verify is aborted after LLM_VERIFY_TIMEOUT_MS (wizard + Model settings). */
export const LLM_VERIFY_TIMEOUT_MESSAGE =
  "Verification timed out after 30 seconds. The LLM endpoint may be slow, unreachable, or blocked by a firewall or proxy. Check the URL, credentials, and network, then try again.";

function isVerifyAbortError(e: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && e instanceof DOMException && e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  );
}

export async function testLlmKey(s: {
  provider: string;
  api_key: string;
  model?: string;
  base_url?: string;
  openai_compatible_model?: string;
  openai_compatible_headers?: string;
} & BedrockCredentials): Promise<{ ok: boolean; message: string }> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), LLM_VERIFY_TIMEOUT_MS);
  try {
    const res = await fetch("/api/settings/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        provider: s.provider,
        api_key: s.api_key,
        model: s.model ?? "",
        aws_region: s.aws_region ?? "",
        aws_access_key_id: s.aws_access_key_id ?? "",
        aws_secret_access_key: s.aws_secret_access_key ?? "",
        aws_session_token: s.aws_session_token ?? "",
        base_url: s.base_url ?? "",
        openai_compatible_model: s.openai_compatible_model ?? "",
        openai_compatible_headers: s.openai_compatible_headers ?? "",
      }),
    });
    if (!res.ok) {
      let detail = "Test request failed";
      try {
        const err = await res.json();
        const d = err?.detail;
        detail = typeof d === "string" ? d : d != null ? JSON.stringify(d) : detail;
      } catch {
        /* ignore */
      }
      return { ok: false, message: detail };
    }
    return res.json() as Promise<{ ok: boolean; message: string }>;
  } catch (e) {
    if (isVerifyAbortError(e)) {
      return { ok: false, message: LLM_VERIFY_TIMEOUT_MESSAGE };
    }
    throw e;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function saveLlmSettings(s: {
  provider: string;
  api_key: string;
  model?: string;
  enable_prompt_cache?: boolean;
  base_url?: string;
  openai_compatible_model?: string;
  openai_compatible_headers?: string;
} & BedrockCredentials): Promise<void> {
  const res = await fetch("/api/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: s.provider,
      api_key: s.api_key,
      model: s.model ?? "",
      aws_region: s.aws_region ?? "",
      aws_access_key_id: s.aws_access_key_id ?? "",
      aws_secret_access_key: s.aws_secret_access_key ?? "",
      aws_session_token: s.aws_session_token ?? "",
      enable_prompt_cache: s.enable_prompt_cache ?? true,
      base_url: s.base_url ?? "",
      openai_compatible_model: s.openai_compatible_model ?? "",
      openai_compatible_headers: s.openai_compatible_headers ?? "",
    }),
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

// --- Connectors ---

export interface ConnectorStatus {
  type: string;
  package: string;
  installed: boolean;
}

export async function getConnectorStatus(type: string): Promise<ConnectorStatus> {
  const res = await fetch(`/api/connectors/${type}/status`);
  if (!res.ok) throw new Error(`Failed to check connector status for ${type}`);
  return res.json();
}

export async function installConnector(type: string): Promise<void> {
  const res = await fetch(`/api/connectors/${type}/install`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Failed to install connector ${type}`);
  }
}

export interface ConnectorTestResult {
  ok: boolean;
  message: string;
}

export async function testConnectorConfig(
  type: string,
  config: Record<string, string>,
  secrets: Record<string, string> = {}
): Promise<ConnectorTestResult> {
  const res = await fetch(`/api/connectors/${type}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config, secrets }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Test failed");
  }
  return res.json();
}

// --- Version / update check ---

export interface VersionInfo {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
}

export async function getVersionInfo(): Promise<VersionInfo> {
  try {
    const res = await fetch("/api/version");
    if (!res.ok) throw new Error("Failed");
    return res.json();
  } catch {
    return { current_version: "unknown", latest_version: null, update_available: false };
  }
}

export interface Release {
  tag_name: string;
  name: string;
  published_at: string;
  body: string;
  html_url: string;
  prerelease: boolean;
}

export async function getReleases(): Promise<Release[]> {
  try {
    const res = await fetch("/api/releases");
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}
