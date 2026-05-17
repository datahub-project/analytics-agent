import { useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, Copy, Check } from "lucide-react";

interface Props {
  payload: {
    error: string;
    error_class?: string;
    traceback?: string;
  };
}

export function ErrorMessage({ payload }: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const hasTraceback = Boolean(payload.traceback);

  const copy = async () => {
    if (!payload.traceback) return;
    await navigator.clipboard.writeText(payload.traceback);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="max-w-[90%] rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 text-xs">
      <div className="flex items-start gap-2 px-3 py-2">
        <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
        <span className="font-mono leading-relaxed flex-1 break-words">{payload.error}</span>
        {hasTraceback && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1 text-[10px] uppercase tracking-wider opacity-70 hover:opacity-100 transition-opacity"
            title={open ? "Hide stack trace" : "Show stack trace"}
          >
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {open ? "details" : "details"}
          </button>
        )}
      </div>
      {hasTraceback && open && (
        <div className="px-3 pb-2">
          <div className="relative">
            <pre className="text-[11px] font-mono whitespace-pre-wrap break-words bg-red-100/60 dark:bg-red-950/50 rounded p-2 max-h-96 overflow-auto border border-red-200/60">
              {payload.traceback}
            </pre>
            <button
              type="button"
              onClick={copy}
              className="absolute top-1.5 right-1.5 p-1 rounded bg-red-50 dark:bg-red-950/70 border border-red-200/60 opacity-70 hover:opacity-100 transition-opacity"
              title="Copy traceback"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
