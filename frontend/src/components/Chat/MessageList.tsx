import { Fragment, useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import type { InterruptDecision, UIMessage } from "@/types";
import { TextMessage } from "./messages/TextMessage";
import { AgentWorkBlock } from "./messages/AgentWorkBlock";
import { ChartMessage } from "./messages/ChartMessage";
import { groupIntoTurns } from "@/lib/groupMessages";

interface Props {
  messages: UIMessage[];
  isStreaming?: boolean;
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
  pendingInterruptId?: string | null;
  onResolveInterrupt?: (decisions: InterruptDecision[]) => void | Promise<void>;
  onTrustSession?: () => void;
  onFollowUp?: (question: string) => void;
}

export function MessageList({
  messages,
  isStreaming = false,
  showReasoning = true,
  onChartError,
  pendingInterruptId,
  onResolveInterrupt,
  onTrustSession,
  onFollowUp,
}: Props) {
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
              pendingInterruptId={pendingInterruptId ?? undefined}
              onResolveInterrupt={onResolveInterrupt}
              onTrustSession={onTrustSession}
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

          {/* Follow-up chips — from the agent's typed response_format. Each
              chip submits as the next user turn when clicked. */}
          {group.followUps.length > 0 && !group.isActivelyStreaming && onFollowUp && (
            <div className="flex flex-wrap gap-2 pl-1 -mt-1" data-print-hide>
              {group.followUps.map((q, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onFollowUp(q)}
                  className="text-xs px-3 py-1.5 rounded-full border border-border
                             bg-muted/30 hover:bg-muted/60 text-muted-foreground
                             hover:text-foreground transition-colors"
                  title="Send this as your next question"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </Fragment>
      ))}
      {isStreaming && (
        <div
          className="flex items-center gap-2 pl-1 text-xs text-muted-foreground"
          data-print-hide
          aria-live="polite"
        >
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>Thinking…</span>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
