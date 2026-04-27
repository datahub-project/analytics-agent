import { useState, useEffect, useRef } from "react";
import { Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import type { TextPayload, UsagePayload } from "@/types";

function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

interface Props {
  payload: TextPayload;
  isStreaming?: boolean;
  usage?: UsagePayload;
}

export function ThinkingMessage({ payload, isStreaming = false, usage }: Props) {
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState(0);
  const startTimeRef = useRef<number>(Date.now());
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Track elapsed time while streaming
  useEffect(() => {
    if (isStreaming) {
      startTimeRef.current = Date.now();
      const interval = setInterval(() => {
        setElapsedSeconds(Math.round((Date.now() - startTimeRef.current) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    } else {
      // Freeze the final elapsed time
      setElapsedSeconds(Math.max(1, Math.round((Date.now() - startTimeRef.current) / 1000)));
    }
  }, [isStreaming]);

  useEffect(() => {
    if (contentRef.current) {
      setContentHeight(contentRef.current.scrollHeight);
    }
  }, [payload.text, expanded]);

  // While streaming, keep expanded; when done, auto-collapse
  useEffect(() => {
    if (!isStreaming) {
      const t = setTimeout(() => setExpanded(false), 400);
      return () => clearTimeout(t);
    } else {
      setExpanded(true);
    }
  }, [isStreaming]);

  return (
    <div className="max-w-[90%] my-1">
      <style>{`
        @keyframes thinking-flow {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        .thinking-border-active {
          position: relative;
        }
        .thinking-border-active::before {
          content: '';
          position: absolute;
          inset: -1px;
          border-radius: 8px;
          padding: 1px;
          background: linear-gradient(135deg, #6366f1, #8b5cf6, #a78bfa, #6366f1);
          background-size: 300% 300%;
          animation: thinking-flow 2.5s ease infinite;
          -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
          -webkit-mask-composite: xor;
          mask-composite: exclude;
          pointer-events: none;
        }
      `}</style>

      <div
        className={`rounded-lg overflow-hidden border transition-all duration-300 ${
          isStreaming
            ? "thinking-border-active border-transparent bg-muted/30"
            : "border-border bg-muted/20"
        }`}
      >
        {/* Header pill */}
        <button
          onClick={() => !isStreaming && setExpanded((v) => !v)}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left transition-colors ${
            isStreaming
              ? "cursor-default"
              : "hover:bg-muted/40 cursor-pointer"
          }`}
        >
          {/* Icon */}
          <span
            className={`flex-shrink-0 transition-colors duration-300 ${
              isStreaming ? "text-violet-400" : "text-muted-foreground"
            }`}
          >
            <Sparkles className={`w-3.5 h-3.5 ${isStreaming ? "animate-pulse" : ""}`} />
          </span>

          {/* Label */}
          <span
            className={`text-xs font-medium flex-1 transition-colors duration-300 ${
              isStreaming ? "text-violet-400" : "text-muted-foreground"
            }`}
          >
            {isStreaming ? (
              <span className="flex items-center gap-1.5">
                Thinking
                <span className="flex gap-0.5">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1 h-1 rounded-full bg-violet-400 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </span>
              </span>
            ) : (
              <span>
                Thought for
                <span className="text-muted-foreground/60 font-normal ml-1">
                  {elapsedSeconds}s
                </span>
              </span>
            )}
          </span>

          {/* Inline cost — shown when done and usage is known */}
          {usage && !isStreaming && (
            <span className="text-[10px] font-mono text-muted-foreground/45 flex-shrink-0 mr-1">
              ↑{fmt(usage.input_tokens)} ↓{usage.output_tokens}
            </span>
          )}

          {/* Chevron (only when done) */}
          {!isStreaming && (
            <span className="text-muted-foreground/50 transition-transform duration-200">
              {expanded ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
            </span>
          )}
        </button>

        {/* Content — smoothly animated; data-print-expand makes it visible in PDF */}
        <div
          data-print-expand
          style={{
            maxHeight: expanded || isStreaming ? `${Math.min(contentHeight + 24, 320)}px` : "0px",
            opacity: expanded || isStreaming ? 1 : 0,
            transition: "max-height 0.35s cubic-bezier(0.4,0,0.2,1), opacity 0.25s ease",
            overflow: "hidden",
          }}
        >
          <div
            ref={contentRef}
            className="px-3 pb-3 pt-0.5 border-t border-border/50 max-h-72 overflow-y-auto"
          >
            <p
              className="text-xs text-muted-foreground/80 leading-relaxed whitespace-pre-wrap font-mono"
              style={{ fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace" }}
            >
              {payload.text}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
