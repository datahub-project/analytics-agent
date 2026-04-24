import { Fragment, useEffect, useRef } from "react";
import type { UIMessage } from "@/types";
import { TextMessage } from "./messages/TextMessage";
import { AgentWorkBlock } from "./messages/AgentWorkBlock";
import { SelectionChip, type SelectionChipPayload } from "./messages/SelectionChip";
import { groupIntoTurns } from "@/lib/groupMessages";

interface Props {
  messages: UIMessage[];
  isStreaming?: boolean;
  conversationId?: string;
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
}

export function MessageList({ messages, isStreaming = false, conversationId, showReasoning = true, onChartError }: Props) {
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

  const groups = groupIntoTurns(messages, isStreaming);

  return (
    <div id="chat-messages" className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {groups.map((group) => {
        // MCP App iframe-originated user turns render as a compact selection
        // chip (flavor C) — not a full user bubble.
        const isMcpAppSelection =
          group.userMsg?.event_type === "TEXT" &&
          (group.userMsg.payload as Record<string, unknown>).source === "mcp_app";
        return (
          <Fragment key={group.key}>
            {/* User message */}
            {group.userMsg && isMcpAppSelection && (
              <div className="flex flex-col items-start" data-print-role="user">
                <SelectionChip payload={group.userMsg.payload as unknown as SelectionChipPayload} />
              </div>
            )}
            {group.userMsg && !isMcpAppSelection && (
              <div className="flex flex-col items-end" data-print-role="user">
                <TextMessage
                  payload={group.userMsg.payload as never}
                  role="user"
                  isStreaming={false}
                />
              </div>
            )}

            {/* Agent work block — only shown when there are intermediate steps */}
            {group.workMsgs.length > 0 && (
              <AgentWorkBlock
                workMessages={group.workMsgs}
                turnUsage={group.finalMsg?.turnUsage}
                isStreaming={group.isActivelyStreaming}
                showReasoning={showReasoning}
                conversationId={conversationId}
                onChartError={onChartError}
              />
            )}

            {/* Final visible response */}
            {group.finalMsg && (group.finalMsg.payload as { text?: string }).text?.trim() && (
              <div className="flex flex-col items-start" data-print-role="assistant">
                <TextMessage
                  payload={group.finalMsg.payload as never}
                  role="assistant"
                  isStreaming={group.finalMsg.isStreaming}
                />
              </div>
            )}
          </Fragment>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
