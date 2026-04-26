import { useEffect, useRef, useState } from "react";
import { getContextQuality, type ContextQuality } from "@/api/conversations";
import { useConversationsStore } from "@/store/conversations";

function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

interface Props {
  conversationId: string | null;
  isStreaming: boolean;
  messageCount: number;
}

// CSS variable names — resolved per active theme via index.css
const QUALITY_COLOR_VAR: Record<number, string> = {
  1: "var(--quality-poor)",
  2: "var(--quality-poor)",
  3: "var(--quality-fair)",
  4: "var(--quality-good)",
  5: "var(--quality-good)",
};

export function ContextStatusBar({ conversationId, isStreaming, messageCount }: Props) {
  const [quality, setQuality] = useState<ContextQuality | null>(null);
  const usageTotals = useConversationsStore((s) => s.usageTotals);
  const wasStreaming = useRef(false);

  // Reset when switching conversations
  useEffect(() => {
    setQuality(null);
  }, [conversationId]);

  // Fetch when history loads (messageCount transitions 0 → N after getConversation resolves).
  // isStreaming guard prevents fetching mid-turn; re-running when it changes is harmless.
  useEffect(() => {
    if (!conversationId || messageCount < 2 || isStreaming) return;
    getContextQuality(conversationId).then(setQuality).catch(() => {});
  }, [conversationId, messageCount, isStreaming]);

  // Poll every 8s during streaming to catch background quality updates in real time
  useEffect(() => {
    if (!isStreaming || !conversationId) return;
    const id = setInterval(() => {
      getContextQuality(conversationId).then(setQuality).catch(() => {});
    }, 8000);
    return () => clearInterval(id);
  }, [isStreaming, conversationId]);

  // Re-fetch immediately after each streaming turn ends
  useEffect(() => {
    if (wasStreaming.current && !isStreaming && conversationId && messageCount >= 2) {
      getContextQuality(conversationId).then(setQuality).catch(() => {});
    }
    wasStreaming.current = isStreaming;
  }, [isStreaming, conversationId, messageCount]);

  if (!conversationId || messageCount < 2) return null;

  const loading = quality === null;
  const score = quality?.score ?? null;
  const colorVar = score !== null ? QUALITY_COLOR_VAR[score] : undefined;
  const colorStyle = colorVar ? { color: `hsl(${colorVar})` } : undefined;
  const dotStyle = colorVar
    ? { backgroundColor: `hsl(${colorVar})` }
    : { backgroundColor: "hsl(var(--muted-foreground) / 0.4)" };
  const qualityText = quality ? `${quality.label} (${quality.score}/5)` : "…";

  const reason = quality?.breakdown?.reason;

  return (
    <div
      className="flex items-center gap-3 px-5 py-2 text-xs border-t border-border"
      data-print-hide
    >
      <span
        className="relative group flex items-center gap-2 font-semibold cursor-default flex-shrink-0 text-muted-foreground"
        style={colorStyle}
      >
        <span
          className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${loading ? "animate-pulse" : ""}`}
          style={dotStyle}
        />
        Context Quality:{" "}
        {loading ? (
          <span className="inline-flex items-center gap-0.5 text-muted-foreground/60">
            <span className="animate-bounce [animation-delay:0ms]">·</span>
            <span className="animate-bounce [animation-delay:150ms]">·</span>
            <span className="animate-bounce [animation-delay:300ms]">·</span>
          </span>
        ) : qualityText}
        {reason && (
          <span className="
            pointer-events-none absolute bottom-full left-0 mb-2 w-72
            px-3 py-2 rounded-lg text-xs font-normal leading-relaxed whitespace-normal
            bg-foreground text-background shadow-lg
            opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-50
          ">
            {reason}
          </span>
        )}
      </span>
      <span className="text-muted-foreground/50">·</span>
      <span className="text-muted-foreground">
        Tip: type{" "}
        <kbd className="font-mono bg-muted border border-border px-1 py-0.5 rounded text-[11px] font-medium">
          /improve-context
        </kbd>{" "}
        to improve future conversations
      </span>

      {usageTotals.calls > 0 && (
        <div className="relative group ml-auto flex-shrink-0">
          <span className="text-[11px] text-muted-foreground font-mono px-2 py-0.5
                           rounded border border-border cursor-default">
            ↑{fmt(usageTotals.input_tokens)} ↓{fmt(usageTotals.output_tokens)}
          </span>
          <div className="pointer-events-none absolute bottom-full right-0 mb-1 z-10
                          min-w-[180px] px-2.5 py-1.5 rounded-md
                          bg-foreground text-background text-[11px] font-mono
                          opacity-0 group-hover:opacity-100 transition-opacity duration-150
                          shadow-lg">
            <div className="flex justify-between gap-4 mb-1 pb-1 border-b border-background/20 opacity-70">
              <span>Session</span>
              <span>{usageTotals.calls} call{usageTotals.calls === 1 ? "" : "s"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="opacity-70">Input</span>
              <span>{usageTotals.input_tokens.toLocaleString()}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="opacity-70">Output</span>
              <span>{usageTotals.output_tokens.toLocaleString()}</span>
            </div>
            {usageTotals.cache_read_tokens > 0 && (
              <div className="flex justify-between gap-4">
                <span className="opacity-70">Cache read</span>
                <span>{usageTotals.cache_read_tokens.toLocaleString()}</span>
              </div>
            )}
            {usageTotals.cache_creation_tokens > 0 && (
              <div className="flex justify-between gap-4">
                <span className="opacity-70">Cache write</span>
                <span>{usageTotals.cache_creation_tokens.toLocaleString()}</span>
              </div>
            )}
            <div className="flex justify-between gap-4 mt-1 pt-1 border-t border-background/20 font-semibold">
              <span className="opacity-70">Total</span>
              <span>{usageTotals.total_tokens.toLocaleString()}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
