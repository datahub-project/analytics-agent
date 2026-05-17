import { useState } from "react";
import { MessageCircleQuestion, X } from "lucide-react";
import type { InterruptDecision } from "@/types";

interface Props {
  question: string;
  options?: string[];
  resolved?: boolean;
  onAnswer?: (decision: InterruptDecision) => void | Promise<void>;
}

export function AskUserCard({ question, options, resolved, onAnswer }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (answer: string) => {
    if (!onAnswer || busy || resolved || !answer.trim()) return;
    setBusy(true);
    try {
      // Edit decision: replace the placeholder `answer=""` with the user's
      // text. The harness re-runs the tool body with this answer so the
      // agent's next ToolMessage carries the user's reply verbatim.
      await onAnswer({
        type: "edit",
        edited_action: {
          name: "ask_user",
          args: { question, options: options ?? [], answer: answer.trim() },
        },
      });
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    if (!onAnswer || busy || resolved) return;
    setBusy(true);
    try {
      await onAnswer({ type: "reject", message: "User skipped this question." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-[90%] my-2 rounded-lg border-2 border-blue-500/40 bg-blue-50/30 dark:bg-blue-950/20">
      <div className="px-4 py-3">
        <div className="flex items-center gap-2 mb-3">
          <MessageCircleQuestion className="w-4 h-4 text-blue-600 dark:text-blue-400" />
          <span className="font-semibold text-sm text-blue-900 dark:text-blue-100">
            {resolved ? "Answered" : "Agent is asking"}
          </span>
        </div>

        <div className="text-sm mb-3 leading-relaxed">{question}</div>

        {options && options.length > 0 && !resolved && (
          <div className="flex flex-wrap gap-2 mb-3">
            {options.map((opt) => (
              <button
                key={opt}
                onClick={() => submit(opt)}
                disabled={busy}
                className="px-3 py-1.5 text-xs rounded-full border border-blue-500/40
                           bg-blue-50 dark:bg-blue-950/40 hover:bg-blue-100
                           dark:hover:bg-blue-900/50 transition-colors disabled:opacity-50"
              >
                {opt}
              </button>
            ))}
          </div>
        )}

        {!resolved && (
          <div className="flex items-center gap-2">
            <input
              className="flex-1 px-3 py-1.5 text-sm border border-border rounded-lg bg-background"
              placeholder={
                options && options.length > 0
                  ? "…or type a custom answer"
                  : "Type your answer"
              }
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit(text)}
              disabled={busy}
              autoFocus
            />
            <button
              className="px-3 py-1.5 text-xs rounded-lg bg-blue-600 text-white
                         hover:bg-blue-700 disabled:opacity-50"
              onClick={() => submit(text)}
              disabled={busy || !text.trim()}
            >
              Send answer
            </button>
            <button
              className="px-2 py-1.5 text-xs rounded-lg border border-border
                         text-muted-foreground hover:bg-muted/50 disabled:opacity-50
                         inline-flex items-center gap-1"
              onClick={skip}
              disabled={busy}
              title="Skip this question — agent will continue without an answer"
            >
              <X className="w-3.5 h-3.5" />
              Skip
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
