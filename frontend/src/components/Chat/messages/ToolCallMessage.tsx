import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import type { ToolCallPayload, ToolResultPayload } from "@/types";

interface ToolCallProps {
  payload: ToolCallPayload;
}

interface ToolResultProps {
  payload: ToolResultPayload;
}

export function ToolCallMessage({ payload }: ToolCallProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="max-w-[90%]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Wrench className="w-3.5 h-3.5" />
        <span className="font-mono">{payload.tool_name}</span>
        {open ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
      </button>
      {open && (
        <pre className="mt-1 px-3 py-2 text-xs bg-muted/50 rounded border border-border overflow-x-auto">
          {JSON.stringify(payload.tool_input, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function ToolResultMessage({ payload }: ToolResultProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="max-w-[90%]">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 text-xs transition-colors ${
          payload.is_error
            ? "text-red-500 hover:text-red-600"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <span className="font-mono">↳ {payload.tool_name}</span>
        {open ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
      </button>
      {open && (
        <pre className="mt-1 px-3 py-2 text-xs bg-muted/50 rounded border border-border overflow-x-auto max-h-48">
          {payload.result}
        </pre>
      )}
    </div>
  );
}
