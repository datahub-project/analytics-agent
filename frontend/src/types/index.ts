export type SSEEventType =
  | "TEXT"
  | "THINKING"
  | "TOOL_CALL"
  | "TOOL_RESULT"
  | "SQL"
  | "CHART"
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

// UI message (may be streaming)
export interface UIMessage {
  id: string;
  event_type: SSEEventType;
  role: "user" | "assistant";
  payload: Record<string, unknown>;
  isStreaming?: boolean;
  isThinking?: boolean; // TEXT message that precedes a tool call
}
