import type { UsagePayload } from "@/types";

function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function TokenBadge({ usage }: { usage: UsagePayload }) {
  const hasCache = usage.cache_read_tokens > 0 || usage.cache_creation_tokens > 0;

  return (
    <div className="relative group inline-block" data-print-hide>
      <span
        className="inline-flex items-center gap-1 text-[10px] text-muted-foreground
                   px-1.5 py-0.5 rounded border border-border bg-background/60 font-mono
                   cursor-default"
      >
        ↑{fmt(usage.input_tokens)} ↓{fmt(usage.output_tokens)}
        {hasCache && <span className="opacity-70">·cache</span>}
      </span>
      <div
        className="pointer-events-none absolute top-full left-0 mt-1 z-10
                   min-w-[160px] px-2.5 py-1.5 rounded-md
                   bg-foreground text-background text-[11px] font-mono
                   opacity-0 group-hover:opacity-100 transition-opacity duration-150
                   shadow-lg"
      >
        <div className="flex justify-between gap-4">
          <span className="opacity-70">Input</span>
          <span>{usage.input_tokens.toLocaleString()}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="opacity-70">Output</span>
          <span>{usage.output_tokens.toLocaleString()}</span>
        </div>
        {usage.cache_read_tokens > 0 && (
          <div className="flex justify-between gap-4">
            <span className="opacity-70">Cache read</span>
            <span>{usage.cache_read_tokens.toLocaleString()}</span>
          </div>
        )}
        {usage.cache_creation_tokens > 0 && (
          <div className="flex justify-between gap-4">
            <span className="opacity-70">Cache write</span>
            <span>{usage.cache_creation_tokens.toLocaleString()}</span>
          </div>
        )}
        <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-background/20 font-semibold">
          <span className="opacity-70">Total</span>
          <span>{usage.total_tokens.toLocaleString()}</span>
        </div>
      </div>
    </div>
  );
}
