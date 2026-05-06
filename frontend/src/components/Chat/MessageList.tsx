import { Fragment, useEffect, useRef } from "react";
import type {
  UIMessage,
  MCPAppPayload,
  ProposalsPayload,
  ProposalResultsPayload,
  SSEEvent,
} from "@/types";
import { TextMessage } from "./messages/TextMessage";
import { AgentWorkBlock } from "./messages/AgentWorkBlock";
import { SelectionChip, type SelectionChipPayload } from "./messages/SelectionChip";
import { MCPAppMessage } from "./messages/MCPAppMessage";
import { ProposalsMessage } from "./messages/ProposalsMessage";
import { ProposalResultsMessage } from "./messages/ProposalResultsMessage";
import { groupIntoTurns } from "@/lib/groupMessages";

interface Props {
  messages: UIMessage[];
  isStreaming?: boolean;
  conversationId?: string;
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
  onProposalStream?: (
    stream: AsyncIterator<SSEEvent>,
    userPayload: {
      text: string;
      display_text: string;
      origin_message_id: string;
      selected_ids: string[];
    }
  ) => void;
  /** Refinement chat from inside a proposals card; renders as a normal user bubble. */
  onProposalRefineStream?: (
    stream: AsyncIterator<SSEEvent>,
    userText: string
  ) => void;
}

export function MessageList({
  messages,
  isStreaming = false,
  conversationId,
  showReasoning = true,
  onChartError,
  onProposalStream,
  onProposalRefineStream,
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
      {groups.map((group) => {
        // MCP App / proposal-select user turns render as a compact selection
        // chip (flavor C) — not a full user bubble.
        const userSource = (group.userMsg?.payload as Record<string, unknown> | undefined)?.source;
        const isMcpAppSelection =
          group.userMsg?.event_type === "TEXT" &&
          (userSource === "mcp_app" || userSource === "proposal_select");
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
                onChartError={onChartError}
              />
            )}

            {/* Interactive cards (MCP apps / proposals / results) — sibling to work block, never collapses */}
            {group.interactiveMsgs.map((msg) => {
              if (msg.event_type === "MCP_APP" && conversationId) {
                return (
                  <div key={msg.id} className="flex flex-col items-start">
                    <MCPAppMessage
                      messageId={msg.id}
                      conversationId={conversationId}
                      payload={msg.payload as unknown as MCPAppPayload}
                    />
                  </div>
                );
              }
              if (msg.event_type === "PROPOSALS" && conversationId) {
                const submitted = messages.some(
                  (m) =>
                    m.role === "user" &&
                    (m.payload as Record<string, unknown>).source === "proposal_select" &&
                    (m.payload as Record<string, unknown>).origin_message_id === msg.id
                );
                return (
                  <div key={msg.id} className="flex flex-col items-start">
                    <ProposalsMessage
                      messageId={msg.id}
                      conversationId={conversationId}
                      payload={msg.payload as unknown as ProposalsPayload}
                      submitted={submitted}
                      onStream={(stream, userPayload) =>
                        onProposalStream?.(stream, userPayload)
                      }
                      onRefineStream={
                        onProposalRefineStream
                          ? (stream, userText) => onProposalRefineStream(stream, userText)
                          : undefined
                      }
                    />
                  </div>
                );
              }
              if (msg.event_type === "PROPOSAL_RESULTS") {
                return (
                  <div key={msg.id} className="flex flex-col items-start">
                    <ProposalResultsMessage
                      payload={msg.payload as unknown as ProposalResultsPayload}
                    />
                  </div>
                );
              }
              return null;
            })}

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
