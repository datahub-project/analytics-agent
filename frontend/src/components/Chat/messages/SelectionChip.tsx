/**
 * SelectionChip — compact pill rendered when an MCP App iframe posts a
 * `ui/message` on behalf of the user (flavor C).
 *
 * Appears anchored under the selector iframe that originated the turn
 * (referenced by origin_message_id in the persisted payload) instead of
 * rendering a full user-bubble. Keeps the transcript auditable without a
 * phantom "I picked X" user turn cluttering the conversation.
 */

import { MousePointerClick } from "lucide-react";

export interface SelectionChipPayload {
  /** Agent-facing text (may be verbose to prevent LLM re-disambiguation). */
  text: string;
  /** Optional short label for display; falls back to `text` if absent. */
  display_text?: string;
  source: "mcp_app";
  app_id?: string;
  origin_message_id?: string;
}

interface Props {
  payload: SelectionChipPayload;
}

export function SelectionChip({ payload }: Props) {
  const label = payload.display_text?.trim() || payload.text;
  return (
    <div
      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-border bg-muted/60 text-sm text-foreground/80 max-w-xs truncate"
      title={label}
      data-origin-message-id={payload.origin_message_id}
    >
      <MousePointerClick className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate">{label}</span>
    </div>
  );
}
