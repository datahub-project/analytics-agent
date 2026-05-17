import { useState } from "react";
import { ShieldCheck, ShieldX, Pencil, AlertTriangle, Infinity as InfinityIcon } from "lucide-react";
import type { InterruptPayload, InterruptDecision } from "@/types";
import { AskUserCard } from "./AskUserCard";

interface Props {
  payload: InterruptPayload;
  resolved?: boolean;
  onDecide?: (decisions: InterruptDecision[]) => void | Promise<void>;
  onTrustSession?: () => void;
}

export function InterruptCard({ payload, resolved, onDecide, onTrustSession }: Props) {
  // ask_user is a special-case interrupt that asks the user a question
  // rather than gating a real mutation. Render a friendlier card.
  if (payload.actions?.length === 1 && payload.actions[0].tool_name === "ask_user") {
    const action = payload.actions[0];
    const args = action.tool_input as { question?: string; options?: string[] };
    return (
      <AskUserCard
        question={args.question ?? ""}
        options={args.options ?? []}
        resolved={resolved}
        onAnswer={(d) => onDecide?.([d])}
      />
    );
  }
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [edited, setEdited] = useState<Record<string, unknown>>({});
  const [rejectReason, setRejectReason] = useState("");
  const [rejecting, setRejecting] = useState(false);

  if (!payload.actions?.length) return null;

  const submit = async (decisions: InterruptDecision[]) => {
    if (busy || resolved || !onDecide) return;
    setBusy(true);
    try {
      await onDecide(decisions);
    } finally {
      setBusy(false);
    }
  };

  const approveAll = () =>
    submit(payload.actions.map(() => ({ type: "approve" as const })));
  const rejectAll = (msg: string) =>
    submit(payload.actions.map(() => ({ type: "reject" as const, message: msg })));
  const submitEdit = (idx: number) => {
    const action = payload.actions[idx];
    const decisions: InterruptDecision[] = payload.actions.map((a, i) =>
      i === idx
        ? { type: "edit", edited_action: { name: a.tool_name, args: edited } }
        : { type: "approve" }
    );
    submit(decisions);
  };

  return (
    <div className="max-w-[90%] my-2 rounded-lg border-2 border-amber-500/50 bg-amber-50/30 dark:bg-amber-950/20">
      <div className="px-4 py-3">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
          <span className="font-semibold text-sm text-amber-900 dark:text-amber-100">
            {resolved ? "Reviewed action" : "Approval required"}
          </span>
          {resolved && (
            <span className="text-xs text-muted-foreground italic">already decided</span>
          )}
        </div>

        {payload.actions.map((action, idx) => (
          <div key={idx} className="mb-2 last:mb-0">
            <div className="text-sm">
              Agent wants to call{" "}
              <code className="px-1.5 py-0.5 bg-muted rounded text-xs font-mono">
                {action.tool_name}
              </code>
              {action.description && (
                <span className="text-muted-foreground"> — {action.description}</span>
              )}
            </div>
            <pre className="mt-2 px-3 py-2 text-xs bg-muted/70 rounded border border-border overflow-x-auto max-h-48">
              {JSON.stringify(
                editing === idx ? edited : action.tool_input,
                null,
                2
              )}
            </pre>
            {editing === idx && !resolved && (
              <textarea
                className="mt-2 w-full text-xs font-mono px-2 py-1 border border-border rounded bg-background"
                rows={Math.min(8, JSON.stringify(action.tool_input, null, 2).split("\n").length + 2)}
                value={JSON.stringify(edited, null, 2)}
                onChange={(e) => {
                  try {
                    setEdited(JSON.parse(e.target.value));
                  } catch {
                    /* keep typing */
                  }
                }}
              />
            )}
          </div>
        ))}

        {!resolved && (
          <div className="flex flex-wrap items-center gap-2 mt-3 pt-2 border-t border-amber-500/30">
            {rejecting ? (
              <>
                <input
                  className="flex-1 px-2 py-1 text-xs border border-border rounded bg-background"
                  placeholder="Reason for rejecting (optional)"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  autoFocus
                />
                <button
                  className="px-3 py-1 text-xs rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                  disabled={busy}
                  onClick={() => rejectAll(rejectReason || "User rejected the action.")}
                >
                  Confirm reject
                </button>
                <button
                  className="px-3 py-1 text-xs rounded border hover:bg-muted"
                  onClick={() => setRejecting(false)}
                  disabled={busy}
                >
                  Cancel
                </button>
              </>
            ) : editing !== null ? (
              <>
                <button
                  className="px-3 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                  disabled={busy}
                  onClick={() => submitEdit(editing)}
                >
                  Approve with edits
                </button>
                <button
                  className="px-3 py-1 text-xs rounded border hover:bg-muted"
                  onClick={() => setEditing(null)}
                  disabled={busy}
                >
                  Cancel edit
                </button>
              </>
            ) : (
              <>
                <button
                  className="px-3 py-1 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 inline-flex items-center gap-1"
                  disabled={busy}
                  onClick={approveAll}
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  Approve
                </button>
                <button
                  className="px-3 py-1 text-xs rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 inline-flex items-center gap-1"
                  disabled={busy}
                  onClick={() => setRejecting(true)}
                >
                  <ShieldX className="w-3.5 h-3.5" />
                  Reject
                </button>
                {payload.actions[0]?.allowed_decisions?.includes("edit") && (
                  <button
                    className="px-3 py-1 text-xs rounded border hover:bg-muted disabled:opacity-50 inline-flex items-center gap-1"
                    disabled={busy}
                    onClick={() => {
                      setEdited(payload.actions[0].tool_input);
                      setEditing(0);
                    }}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                    Edit args
                  </button>
                )}
                {onTrustSession && (
                  <button
                    className="ml-auto px-3 py-1 text-xs rounded border hover:bg-muted disabled:opacity-50 inline-flex items-center gap-1"
                    disabled={busy}
                    title="Approve this and auto-approve any further interrupts in this conversation"
                    onClick={() => {
                      onTrustSession();
                      approveAll();
                    }}
                  >
                    <InfinityIcon className="w-3.5 h-3.5" />
                    Approve & trust session
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
