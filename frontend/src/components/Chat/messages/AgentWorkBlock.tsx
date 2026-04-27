import { useState, useEffect, useRef, useMemo } from "react";
import { Settings2, ChevronDown, ChevronRight } from "lucide-react";
import type { UIMessage, TurnUsage } from "@/types";
import { shouldShowSeparator, getSepUsage } from "@/lib/groupMessages";
import { ThinkingMessage } from "./ThinkingMessage";
import { ToolCallMessage, ToolResultMessage } from "./ToolCallMessage";
import { SqlMessage } from "./SqlMessage";
import { ChartMessage } from "./ChartMessage";
import { ErrorMessage } from "./ErrorMessage";

function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

interface Props {
  workMessages: UIMessage[];
  turnUsage?: TurnUsage;
  isStreaming?: boolean;
  showReasoning?: boolean;
  onChartError?: (error: string) => void;
}

export function AgentWorkBlock({
  workMessages,
  turnUsage,
  isStreaming = false,
  showReasoning = true,
  onChartError,
}: Props) {
  const [expanded, setExpanded] = useState(isStreaming);
  const bodyRef = useRef<HTMLDivElement>(null);
  const startRef = useRef<number>(Date.now());
  const [liveElapsed, setLiveElapsed] = useState(0);
  const frozenElapsed = useRef<number | null>(null);

  // Compute elapsed from timestamps for completed turns (loaded from DB)
  const tsElapsed = useMemo(() => {
    if (workMessages.length === 0) return 0;
    const t0 = workMessages.find((m) => m.created_at)?.created_at;
    const tN = [...workMessages].reverse().find((m) => m.created_at)?.created_at;
    if (!t0 || !tN) return 0;
    return Math.max(1, Math.round((new Date(tN).getTime() - new Date(t0).getTime()) / 1000));
  }, [workMessages]);

  // Live timer while streaming
  useEffect(() => {
    if (!isStreaming) {
      if (frozenElapsed.current === null && liveElapsed > 0) {
        frozenElapsed.current = liveElapsed;
      }
      return;
    }
    startRef.current = Date.now();
    const iv = setInterval(() => {
      setLiveElapsed(Math.round((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(iv);
  }, [isStreaming]);

  // Expand while streaming, auto-collapse 600ms after done
  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
    } else {
      const t = setTimeout(() => setExpanded(false), 600);
      return () => clearTimeout(t);
    }
  }, [isStreaming]);

  // Auto-scroll to bottom while streaming
  useEffect(() => {
    if (isStreaming && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [workMessages.length, isStreaming]);

  const elapsedSeconds = isStreaming
    ? liveElapsed
    : (frozenElapsed.current ?? (liveElapsed > 0 ? liveElapsed : tsElapsed));

  const toolCallCount = workMessages.filter((m) => m.event_type === "TOOL_CALL").length;

  return (
    <div className="w-full my-1.5" data-print-hide>
      {/* Header bar */}
      <button
        aria-expanded={expanded}
        onClick={() => { if (!isStreaming) setExpanded((v) => !v); }}
        className={`w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors
          border border-border/70
          ${expanded ? "rounded-t-lg rounded-b-none" : "rounded-lg hover:bg-muted/30"}
          ${isStreaming ? "cursor-default bg-muted/10" : "cursor-pointer bg-muted/5"}`}
      >
        <Settings2
          className={`w-3.5 h-3.5 flex-shrink-0 transition-colors ${
            isStreaming ? "text-primary animate-spin" : "text-muted-foreground/60"
          }`}
          style={isStreaming ? { animationDuration: "3s" } : undefined}
        />

        <span className={`text-xs flex-1 font-medium ${isStreaming ? "text-foreground" : "text-muted-foreground"}`}>
          {isStreaming ? (
            <span>
              Working
              {liveElapsed > 0 && <span className="opacity-70"> · {liveElapsed}s</span>}
              <span className="inline-flex gap-0.5 ml-1.5">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1 h-1 rounded-full bg-primary/60 animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </span>
            </span>
          ) : (
            <span>
              Worked for {elapsedSeconds > 0 ? `${elapsedSeconds}s` : "—"}
              {toolCallCount > 0 && (
                <span className="opacity-50 ml-1.5">· {toolCallCount} tool call{toolCallCount !== 1 ? "s" : ""}</span>
              )}
            </span>
          )}
        </span>

        {turnUsage && !isStreaming && (
          <span className="text-[10px] font-mono text-muted-foreground/45 flex-shrink-0">
            ↑{fmt(turnUsage.input_tokens)} ↓{fmt(turnUsage.output_tokens)}
            {turnUsage.calls > 1 && <span className="opacity-60"> · {turnUsage.calls}</span>}
          </span>
        )}

        {!isStreaming && (
          <span className="text-muted-foreground/40 flex-shrink-0">
            {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </span>
        )}
      </button>

      {/* Bounded body */}
      {expanded && (
        <div
          ref={bodyRef}
          className="border border-t-0 border-border/70 rounded-b-lg px-3 py-2 space-y-1 max-h-72 overflow-y-auto bg-muted/5"
        >
          {workMessages.map((msg, idx) => {
            const showSep = shouldShowSeparator(workMessages, idx);
            const sepUsage = showSep ? getSepUsage(workMessages, idx) : undefined;

            return (
              <div key={msg.id}>
                {showSep && (
                  <div className="flex items-center gap-2 py-1">
                    <div className="flex-1 h-px bg-border/50" />
                    {sepUsage && (
                      <span className="text-[9px] font-mono text-muted-foreground/40 flex-shrink-0">
                        ↑{fmt(sepUsage.input_tokens)} ↓{sepUsage.output_tokens}
                      </span>
                    )}
                    <div className="flex-1 h-px bg-border/50" />
                  </div>
                )}

                {msg.event_type === "TEXT" && msg.isThinking && showReasoning && (
                  <ThinkingMessage payload={msg.payload as never} isStreaming={false} usage={msg.usage} />
                )}
                {msg.event_type === "THINKING" && (
                  <ThinkingMessage payload={msg.payload as never} />
                )}
                {msg.event_type === "TOOL_CALL" && (
                  <ToolCallMessage payload={msg.payload as never} />
                )}
                {msg.event_type === "TOOL_RESULT" && (
                  <ToolResultMessage payload={msg.payload as never} />
                )}
                {msg.event_type === "SQL" && (
                  <SqlMessage payload={msg.payload as never} />
                )}
                {msg.event_type === "CHART" && (
                  <ChartMessage payload={msg.payload as never} onRenderError={onChartError} />
                )}
                {msg.event_type === "ERROR" && (
                  <ErrorMessage payload={msg.payload as never} />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
