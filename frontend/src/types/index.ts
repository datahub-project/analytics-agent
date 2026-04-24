export type SSEEventType =
  | "TEXT"
  | "THINKING"
  | "TOOL_CALL"
  | "TOOL_RESULT"
  | "SQL"
  | "CHART"
  | "MCP_APP"
  | "USAGE"
  | "COMPLETE"
  | "ERROR";

export interface SSEEvent {
  event: SSEEventType;
  conversation_id: string;
  message_id: string;
  payload: Record<string, unknown>;
}

export interface TextPayload {
  text: string;
}

export interface ToolCallPayload {
  tool_name: string;
  tool_input: Record<string, unknown>;
}

export interface ToolResultPayload {
  tool_name: string;
  result: string;
  is_error: boolean;
}

export interface SqlPayload {
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  truncated: boolean;
}

export interface ChartPayload {
  vega_lite_spec: Record<string, unknown>;
  reasoning: string;
  chart_type: string;
}

export interface UsagePayload {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  node: string;
}

export interface MCPAppPayload {
  app_id: string;
  connection_key: string;
  server_name: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  /**
   * Structured CallToolResult content (list of MCP content blocks, typically
   * `[{type: "text", text: "..."}]`). Forwarded verbatim to the iframe app via
   * `ui/notifications/tool-result`.
   */
  tool_result: unknown;
  resource_uri: string;
  csp: string | null;
  permissions: string[];
}

export interface Engine {
  name: string;
  type: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  engine_name: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface MessageRecord {
  id: string;
  event_type: SSEEventType;
  role: "user" | "assistant";
  payload: Record<string, unknown>;
  sequence: number;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageRecord[];
  is_streaming?: boolean;
}

export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  calls: number;
}

// UI message (may be streaming)
export interface UIMessage {
  id: string;
  event_type: SSEEventType;
  role: "user" | "assistant";
  payload: Record<string, unknown>;
  isStreaming?: boolean;
  isThinking?: boolean; // TEXT message that precedes a tool call
  usage?: UsagePayload; // per-call cost (shown inline on thinking blocks / step separators)
  turnUsage?: TurnUsage; // aggregated cost for the whole agent turn (shown on final response)
  created_at?: string; // ISO timestamp for elapsed-time computation
}
