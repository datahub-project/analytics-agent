/**
 * ProposalsMessage — renders a set of agent-proposed documentation changes
 * as an interactive card. The user selects which proposals to apply and
 * clicks Submit (or Skip to bypass all). Once submitted, the card
 * transitions to a disabled read-only state.
 */

import { useState, useEffect } from "react";
import { FileText, FilePlus, Tag, CheckSquare, Square, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ProposalItem, ProposalsPayload } from "@/types";
import { sendProposalSelection } from "@/api/conversations";

interface Props {
  messageId: string;
  conversationId: string;
  payload: ProposalsPayload;
  submitted: boolean;
  onStream: (
    stream: AsyncIterator<import("@/types").SSEEvent>,
    userPayload: {
      text: string;
      display_text: string;
      origin_message_id: string;
      selected_ids: string[];
    }
  ) => void;
}

const KIND_META: Record<
  ProposalItem["kind"],
  { label: string; className: string; icon: React.ReactNode }
> = {
  new_doc: {
    label: "New doc",
    className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
    icon: <FilePlus className="w-3 h-3" />,
  },
  update_doc: {
    label: "Update doc",
    className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
    icon: <FileText className="w-3 h-3" />,
  },
  fix_description: {
    label: "Fix description",
    className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400",
    icon: <Tag className="w-3 h-3" />,
  },
};

export function ProposalsMessage({ messageId, conversationId, payload, submitted, onStream }: Props) {
  const { proposals } = payload;
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Clear the spinner once the parent confirms submission (selection chip appended)
  useEffect(() => {
    if (submitted) setIsSubmitting(false);
  }, [submitted]);

  const toggle = (id: string) => {
    if (submitted || isSubmitting) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (submitted || isSubmitting) return;
    setSelected(new Set(proposals.map((p) => p.id)));
  };

  const selectNone = () => {
    if (submitted || isSubmitting) return;
    setSelected(new Set());
  };

  const handleSubmit = async (skipAll = false) => {
    if (submitted || isSubmitting) return;
    setIsSubmitting(true);
    try {
      const ids = skipAll ? [] : Array.from(selected);
      const selectedItems = proposals.filter((p) => ids.includes(p.id));
      const agentText =
        selectedItems.length === 0
          ? "Skip all proposals — make no changes."
          : `Publish the following proposals: ${selectedItems.map((p) => `"${p.title}"`).join(", ")}.`;
      const displayText =
        selectedItems.length === 0
          ? "Skipped proposals"
          : `Selected ${selectedItems.length} proposal${selectedItems.length === 1 ? "" : "s"}`;

      const stream = sendProposalSelection(conversationId, messageId, ids, proposals);
      onStream(stream, {
        text: agentText,
        display_text: displayText,
        origin_message_id: messageId,
        selected_ids: ids,
      });
    } catch {
      setIsSubmitting(false);
    }
  };

  const disabled = submitted || isSubmitting;

  return (
    <div className="w-full rounded-lg border border-border overflow-hidden bg-background">
      {/* Header strip */}
      <div className="flex items-center gap-2 px-3 py-2 bg-muted/40 border-b border-border text-xs text-muted-foreground">
        <FilePlus className="w-3.5 h-3.5 shrink-0" />
        <span className="font-medium">Proposed changes</span>
        <span className="ml-auto shrink-0 opacity-60">
          {proposals.length} proposal{proposals.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Prompt / description */}
      {payload.prompt && (
        <div className="px-4 pt-3 pb-1 text-sm text-muted-foreground prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{payload.prompt}</ReactMarkdown>
        </div>
      )}

      {/* Proposal list */}
      <ul className="divide-y divide-border">
        {proposals.map((proposal) => {
          const meta = KIND_META[proposal.kind];
          const isChecked = selected.has(proposal.id);

          return (
            <li
              key={proposal.id}
              className={`flex gap-3 px-4 py-3 ${disabled ? "" : "cursor-pointer hover:bg-muted/30 transition-colors"}`}
              onClick={() => toggle(proposal.id)}
            >
              {/* Checkbox */}
              <div className="mt-0.5 shrink-0 text-primary">
                {isChecked ? (
                  <CheckSquare className={`w-4 h-4 ${disabled ? "opacity-50" : ""}`} />
                ) : (
                  <Square className={`w-4 h-4 text-muted-foreground ${disabled ? "opacity-50" : ""}`} />
                )}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  {/* Kind badge */}
                  <span
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${meta.className}`}
                  >
                    {meta.icon}
                    {meta.label}
                  </span>
                  <span className="text-sm font-medium text-foreground truncate">
                    {proposal.title}
                  </span>
                </div>
                {proposal.detail && (
                  <div className="text-xs text-muted-foreground prose prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{proposal.detail}</ReactMarkdown>
                  </div>
                )}
                {proposal.target?.field_path && (
                  <p className="mt-1 text-[10px] font-mono text-muted-foreground/70 truncate">
                    {proposal.target.field_path}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-border bg-muted/20">
        {/* Select all / none */}
        {!disabled && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <button
              onClick={(e) => { e.stopPropagation(); selectAll(); }}
              className="hover:text-foreground transition-colors underline-offset-2 hover:underline"
            >
              Select all
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); selectNone(); }}
              className="hover:text-foreground transition-colors underline-offset-2 hover:underline"
            >
              Select none
            </button>
          </div>
        )}
        {disabled && <div />}

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {!disabled && (
            <button
              onClick={(e) => { e.stopPropagation(); void handleSubmit(true); }}
              className="text-xs px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            >
              Skip
            </button>
          )}
          <button
            disabled={disabled}
            onClick={(e) => { e.stopPropagation(); void handleSubmit(false); }}
            className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md font-medium transition-colors
              ${disabled
                ? "bg-primary/40 text-primary-foreground cursor-not-allowed"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
              }`}
          >
            {isSubmitting && <Loader2 className="w-3 h-3 animate-spin" />}
            {submitted ? "Submitted" : isSubmitting ? "Submitting…" : `Submit selected (${selected.size})`}
          </button>
        </div>
      </div>
    </div>
  );
}
