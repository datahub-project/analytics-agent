import { Fragment, useEffect, useRef } from "react";
import type { UIMessage } from "@/types";
import { TextMessage } from "./messages/TextMessage";
import { AgentWorkBlock } from "./messages/AgentWorkBlock";
import { ChartMessage } from "./messages/ChartMessage";
import { groupIntoTurns } from "@/lib/groupMessages";

interface Props {
  messages: UIMessage[];
  isStreaming?: boolean;
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
}

export function MessageList({ messages, isStreaming = false, showReasoning = true, onChartError }: Props) {
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
      {groups.map((group) => (
        <Fragment key={group.key}>
          {/* User message */}
          {group.userMsg && (
            <div className="flex flex-col items-end" data-print-role="user">
              <TextMessage
                payload={group.userMsg.payload as never}
                role="user"
                isStreaming={false}
              />
            </div>
          )}

          {/* Agent work block — tool calls, SQL, thinking. Charts are excluded. */}
          {group.workMsgs.length > 0 && (
            <AgentWorkBlock
              workMessages={group.workMsgs}
              turnUsage={group.finalMsg?.turnUsage}
              isStreaming={group.isActivelyStreaming}
              showReasoning={showReasoning}
              onChartError={onChartError}
            />
          )}

          {/* Charts rendered OUTSIDE the work block so they stay visible when it collapses. */}
          {group.chartMsgs.map((msg) => (
            <div key={msg.id} className="w-full" data-print-role="chart">
              <ChartMessage
                payload={msg.payload as never}
                onRenderError={onChartError}
              />
            </div>
          ))}

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
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
