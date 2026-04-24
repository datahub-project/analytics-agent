/**
 * JSON-RPC 2.0 message types for the MCP Apps postMessage protocol.
 *
 * Phase 1 surface (implemented):
 *   ui/initialize  — app → host: SDK App.connect() handshake request
 *   ui/toolResult  — host → app: push original tool result after initialize ack
 *   ui/ready       — app → host: app has rendered, host hides loading skeleton
 *
 * Phase 2 surface (typed here for forward-compat, not yet wired):
 *   tools/call         — app → host: execute a scoped MCP tool
 *   ui/message         — app → host: send a user turn to the conversation
 *   ui/context/update  — app → host: inject context for the next agent turn
 *   sendOpenLink       — app → host: open an external URL
 */

export const PROTOCOL_VERSION = "2026-01-26";

// ── Base JSON-RPC shapes ────────────────────────────────────────────────────

export interface JsonRpcRequest<P = unknown> {
  jsonrpc: "2.0";
  id: string | number;
  method: string;
  params?: P;
}

export interface JsonRpcNotification<P = unknown> {
  jsonrpc: "2.0";
  method: string;
  params?: P;
}

export interface JsonRpcResponse<R = unknown> {
  jsonrpc: "2.0";
  id: string | number;
  result: R;
}

export interface JsonRpcError {
  jsonrpc: "2.0";
  id: string | number | null;
  error: { code: number; message: string; data?: unknown };
}

export type JsonRpcMessage =
  | JsonRpcRequest
  | JsonRpcNotification
  | JsonRpcResponse
  | JsonRpcError;

// ── Phase 1 ─────────────────────────────────────────────────────────────────

/** app → host: App.connect() sends this; host must ack or app hangs. */
export interface UiInitializeRequest
  extends JsonRpcRequest<{ protocolVersion?: string }> {
  method: "ui/initialize";
}

export interface HostCapabilities {
  tools?: Record<string, unknown>;
  context?: Record<string, unknown>;
  message?: Record<string, unknown>;
  openLink?: Record<string, unknown>;
}

export interface HostInfo {
  name: string;
  version: string;
}

/**
 * Shape of the `ui/initialize` result the host sends back to the app.
 * Mirrors the app-side request shape ({appInfo, appCapabilities, protocolVersion})
 * with host-prefixed names — the MCP Apps SDK's Zod schema on the app side
 * requires all three object fields; omitting any of them causes the SDK to
 * reject App.connect() with `invalid_type` errors.
 */
export interface UiInitializeResult {
  protocolVersion: string;
  hostInfo: HostInfo;
  hostCapabilities: HostCapabilities;
  hostContext: Record<string, unknown>;
}

export interface UiInitializeResponse extends JsonRpcResponse<UiInitializeResult> {}

/**
 * host → app: structured CallToolResult.
 * Per MCP Apps spec §"Notifications (Host → View)" the method name is
 * `ui/notifications/tool-result` and params is the full CallToolResult
 * (with `content: ContentBlock[]`). NOT `ui/toolResult` and NOT `{content: string}`.
 */
export interface McpContentBlock {
  type: string;
  text?: string;
  data?: unknown;
  [k: string]: unknown;
}

export interface CallToolResult {
  content: McpContentBlock[];
  isError?: boolean;
  structuredContent?: Record<string, unknown>;
  _meta?: Record<string, unknown>;
}

export interface UiToolInputNotification
  extends JsonRpcNotification<{ arguments: Record<string, unknown> }> {
  method: "ui/notifications/tool-input";
}

export interface UiToolResultNotification
  extends JsonRpcNotification<CallToolResult> {
  method: "ui/notifications/tool-result";
}

/**
 * app → host notification: handshake complete.
 * Spec §"Lifecycle" uses `ui/notifications/initialized` (mirrors MCP's
 * notifications/initialized). `ui/ready` is our legacy name — kept as alias.
 */
export interface UiInitializedNotification extends JsonRpcNotification {
  method: "ui/notifications/initialized";
}

/**
 * app → host notification: publish the current content size so the host
 * can auto-resize its iframe to fit. Only `height` is honoured — hosts
 * own width and constrain it to the chat column.
 */
export interface UiSizeChangedNotification
  extends JsonRpcNotification<{ height?: number; width?: number }> {
  method: "ui/notifications/size-changed";
}

// ── Phase 2 (typed, not yet wired) ──────────────────────────────────────────

export interface ToolsCallRequest
  extends JsonRpcRequest<{ name: string; arguments?: Record<string, unknown> }> {
  method: "tools/call";
}

/**
 * app → host: send a user turn to the conversation.
 * Per spec §"ui/message": params.content is a content block object
 * `{ type: "text", text: string }`, NOT a plain string.
 */
export interface UiMessageContentBlock {
  type: string;
  text: string;
}

export interface UiMessageRequest
  extends JsonRpcRequest<{ role?: string; content: UiMessageContentBlock }> {
  method: "ui/message";
}

export interface UiContextUpdateNotification
  extends JsonRpcNotification<{ content: unknown }> {
  method: "ui/context/update";
}

export interface SendOpenLinkRequest
  extends JsonRpcRequest<{ url: string }> {
  method: "sendOpenLink";
}

// ── Type guards ──────────────────────────────────────────────────────────────

export function isJsonRpc(msg: unknown): msg is JsonRpcMessage {
  return (
    typeof msg === "object" &&
    msg !== null &&
    (msg as Record<string, unknown>)["jsonrpc"] === "2.0"
  );
}

export function isRequest(msg: JsonRpcMessage): msg is JsonRpcRequest {
  return "method" in msg && "id" in msg;
}

export function isNotification(msg: JsonRpcMessage): msg is JsonRpcNotification {
  return "method" in msg && !("id" in msg);
}
