import { useState } from "react";
import { ChevronDown, ChevronRight, Users } from "lucide-react";
import type { SubagentCallPayload, SubagentResultPayload } from "@/types";

export function SubagentCallMessage({ payload }: { payload: SubagentCallPayload }) {
  return (
    <div className="max-w-[90%] flex items-center gap-1.5 text-xs">
      <Users className="w-3.5 h-3.5 text-primary" />
      <span className="text-muted-foreground">Delegating to</span>
      <span className="font-mono text-primary">{payload.subagent_type || "sub-agent"}</span>
      {payload.description && (
        <span className="text-muted-foreground truncate">— {payload.description}</span>
      )}
    </div>
  );
}

export function SubagentResultMessage({ payload }: { payload: SubagentResultPayload }) {
  const [open, setOpen] = useState(false);
  const preview = payload.result.split("\n")[0]?.slice(0, 80) ?? "";
  return (
    <div className="max-w-[90%]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <span className="font-mono">↳ sub-agent returned</span>
        <span className="text-muted-foreground/60 truncate">{preview}</span>
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>
      {open && (
        <pre className="mt-1 px-3 py-2 text-xs bg-muted/50 rounded border border-border overflow-x-auto max-h-64 whitespace-pre-wrap">
          {payload.result}
        </pre>
      )}
    </div>
  );
}
