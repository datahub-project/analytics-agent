import { useEffect, useRef } from "react";
import type { UIMessage } from "@/types";
import { TextMessage } from "./messages/TextMessage";
import { ThinkingMessage } from "./messages/ThinkingMessage";
import { ToolCallMessage, ToolResultMessage } from "./messages/ToolCallMessage";
import { SqlMessage } from "./messages/SqlMessage";
import { ChartMessage } from "./messages/ChartMessage";
import { ErrorMessage } from "./messages/ErrorMessage";
import { TokenBadge } from "./messages/TokenBadge";

interface Props {
  messages: UIMessage[];
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
}

export function MessageList({ messages, showReasoning = true, onChartError }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        Ask a question about your data
      </div>
    );
  }

  return (
    <div id="chat-messages" className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
          data-print-role={msg.role}
          data-print-hide={msg.event_type === "TOOL_CALL" || msg.event_type === "TOOL_RESULT" ? "" : undefined}
        >
          {msg.event_type === "TEXT" && !msg.isThinking && (
            <TextMessage
              payload={msg.payload as never}
              role={msg.role}
              isStreaming={msg.isStreaming}
            />
          )}
          {msg.event_type === "TEXT" && msg.isThinking && showReasoning && (
            <ThinkingMessage
              payload={msg.payload as never}
              isStreaming={false}
            />
          )}
          {msg.event_type === "THINKING" && (
            <ThinkingMessage payload={msg.payload as never} />
          )}
          {msg.event_type === "TOOL_CALL" && (
            <ToolCallMessage payload={msg.payload as never} />
          )}
          {msg.event_type === "TOOL_RESULT" && (
            <ToolResultMessage payload={msg.payload as never} />
          )}
          {msg.event_type === "SQL" && (
            <SqlMessage payload={msg.payload as never} />
          )}
          {msg.event_type === "CHART" && (
            <ChartMessage payload={msg.payload as never} onRenderError={onChartError} />
          )}
          {msg.event_type === "ERROR" && (
            <ErrorMessage payload={msg.payload as never} />
          )}
          {msg.usage && msg.role === "assistant" && !msg.isStreaming && (
            <div className="mt-1">
              <TokenBadge usage={msg.usage} />
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
