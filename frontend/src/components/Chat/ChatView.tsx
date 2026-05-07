import { useEffect, useCallback, useState, useRef } from "react";
import type { MessageRecord, UsagePayload, TurnUsage } from "@/types";
import { streamMessage, reattachStream } from "@/api/stream";
import { generateTitle, getConversation, createConversation } from "@/api/conversations";
import { Download, X } from "lucide-react";
import { useConversationsStore } from "@/store/conversations";
import { useDisplayStore } from "@/store/display";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import { EngineSelector } from "./EngineSelector";
import { WelcomeView } from "./WelcomeView";
import { ContextStatusBar } from "./ContextStatusBar";
import type { UIMessage } from "@/types";
import { buildUiMessages } from "@/lib/buildUiMessages";
import { v4 as uuidv4 } from "uuid";

export function ChatView() {
  const {
    activeId,
    messages,
    engines,
    isStreaming,
    setMessages,
    setActiveId,
    addConversation,
    appendMessage,
    appendStreamingText,
    resetStreamingText,
    markCurrentAsThinking,
    setStreaming,
    updateConversationTitle,
    conversations,
    usageTotals,
    setUsageTotals,
    addUsage,
    attachUsageToMessage,
    setFinalMsgTurnUsage,
    finalizeStreaming,
  } = useConversationsStore();

  const activeConv = conversations.find((c) => c.id === activeId);
  const pendingFirstMessage = useRef<string | null>(null);
  const chartErrorRetried = useRef(false);
  const streamAbortRef = useRef<AbortController | null>(null);

  // Load conversation history when activeId changes; fire pending first message
  useEffect(() => {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    if (!activeId) {
      setMessages([]);
      return;
    }
    chartErrorRetried.current = false;
    // New conversation from welcome screen — skip history fetch (nothing to load)
    // and fire the first message directly. getConversation would race and overwrite it.
    if (pendingFirstMessage.current) {
      const text = pendingFirstMessage.current;
      pendingFirstMessage.current = null;
      handleSend(text);
      return;
    }

    const snapId = activeId;

    getConversation(snapId).then(async (detail) => {
      // Bail if the user has already switched to a different conversation
      if (activeId !== snapId) return;

      if (!detail.is_streaming) {
        const { messages: uiMsgs, totals } = buildUiMessages(detail.messages);
        setMessages(uiMsgs);
        setUsageTotals(totals);
        return;
      }

      // There is an in-progress agent stream for this conversation.
      // Strip the incomplete in-progress turn (everything after the last user
      // message) — the stream replay will provide those events live.
      const lastUserIdx = detail.messages.reduce(
        (acc, m, i) => (m.role === "user" ? i : acc),
        -1
      );
      const previousMessages = lastUserIdx >= 0
        ? detail.messages.slice(0, lastUserIdx + 1)
        : detail.messages;
      const { messages: prevUiMsgs, totals: prevTotals } = buildUiMessages(previousMessages);
      setMessages(prevUiMsgs);
      setUsageTotals(prevTotals);

      setStreaming(true);
      resetStreamingText();
      const controller = new AbortController();
      streamAbortRef.current = controller;

      let aborted = false;
      try {
        const stream = reattachStream(snapId, controller.signal);
        let result = await stream.next();
        const reattachTurnUsage: TurnUsage = { input_tokens: 0, output_tokens: 0, total_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0, calls: 0 };
        while (!result.done) {
          // Bail if the user switched away while we were awaiting
          if (activeId !== snapId) {
            controller.abort();
            return;
          }
          const event = result.value;
          if (event.event === "TEXT") {
            appendStreamingText((event.payload as { text: string }).text);
          } else if (event.event === "TOOL_CALL") {
            markCurrentAsThinking();
            appendMessage({
              id: event.message_id,
              event_type: event.event,
              role: "assistant",
              payload: event.payload,
            });
          } else if (event.event === "USAGE") {
            const usage = event.payload as unknown as UsagePayload;
            addUsage(usage);
            reattachTurnUsage.input_tokens += usage.input_tokens || 0;
            reattachTurnUsage.output_tokens += usage.output_tokens || 0;
            reattachTurnUsage.total_tokens += usage.total_tokens || 0;
            reattachTurnUsage.cache_read_tokens += usage.cache_read_tokens || 0;
            reattachTurnUsage.cache_creation_tokens += usage.cache_creation_tokens || 0;
            reattachTurnUsage.calls += 1;
            if (usage.model) reattachTurnUsage.model = usage.model;
            if (usage.provider) reattachTurnUsage.provider = usage.provider;
            const state = useConversationsStore.getState();
            const targetId =
              state.streamingTextId ??
              [...state.messages].reverse().find((m) => m.role === "assistant" && m.event_type === "TOOL_CALL")?.id ??
              [...state.messages].reverse().find((m) => m.role === "assistant")?.id;
            if (targetId) attachUsageToMessage(targetId, usage);
          } else if (event.event === "COMPLETE") {
            if (reattachTurnUsage.calls > 0) setFinalMsgTurnUsage({ ...reattachTurnUsage });
          } else {
            appendMessage({
              id: event.message_id,
              event_type: event.event,
              role: "assistant",
              payload: event.payload,
            });
          }
          result = await stream.next();
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          aborted = true;
          return;
        }
        appendMessage({
          id: uuidv4(),
          event_type: "ERROR",
          role: "assistant",
          payload: { error: String(err) },
        });
      } finally {
        streamAbortRef.current = null;
        setStreaming(false);
        if (!aborted && activeId === snapId) {
          // Reload full history from DB to catch anything committed after the
          // initial fetch, then generate/update the title.
          getConversation(snapId).then((refreshed) => {
            if (activeId !== snapId) return;
            const { messages: uiMsgs, totals } = buildUiMessages(refreshed.messages);
            setMessages(uiMsgs);
            setUsageTotals(totals);
          }).catch(() => {});
          generateTitle(snapId).then((r) => {
            if (r.updated) updateConversationTitle(snapId, r.title);
          }).catch(() => {});
        }
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  // Other references (setMessages, appendMessage, etc.) are stable Zustand store
  // actions — their identity never changes, so only activeId needs to re-trigger.
  }, [activeId]);

  const [showReasoning, setShowReasoning] = useState(true);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportIncludeReasoning, setExportIncludeReasoning] = useState(false);

  const handleExport = useCallback(() => {
    document.querySelectorAll("[data-print-expand]").forEach((el) => {
      (el as HTMLElement).style.maxHeight = "none";
      (el as HTMLElement).style.overflow = "visible";
      (el as HTMLElement).style.opacity = "1";
    });

    const slugify = (s: string) =>
      s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

    const appName = slugify(useDisplayStore.getState().appName || "analytics-agent");
    const title   = slugify(activeConv?.title ?? "conversation");
    const ts      = new Date().toISOString().slice(0, 16).replace("T", "-").replace(":", "");
    const filename = `${appName}-${title}-${ts}`;

    const prev = document.title;
    document.title = filename;
    window.print();
    document.title = prev;
    setExportModalOpen(false);
  }, [activeConv?.title]);

  const handleSend = async (text: string) => {
    if (!activeId || isStreaming) return;

    // Append user message immediately
    appendMessage({
      id: uuidv4(),
      event_type: "TEXT",
      role: "user",
      payload: { text },
    });

    setStreaming(true);
    resetStreamingText(); // new turn — reset so TEXT goes to a fresh message

    const conversationId = activeId;
    let aborted = false;
    try {
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const stream = streamMessage(conversationId, text, controller.signal);
      let result = await stream.next();
      const sendTurnUsage: TurnUsage = { input_tokens: 0, output_tokens: 0, total_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0, calls: 0 };
      while (!result.done) {
        const event = result.value;
        if (event.event === "TEXT") {
          appendStreamingText((event.payload as { text: string }).text);
        } else if (event.event === "TOOL_CALL") {
          // Text before this tool call was reasoning — mark it as a thinking block
          markCurrentAsThinking();
          appendMessage({
            id: event.message_id,
            event_type: event.event,
            role: "assistant",
            payload: event.payload,
          });
        } else if (event.event === "USAGE") {
          const usage = event.payload as unknown as UsagePayload;
          addUsage(usage);
          sendTurnUsage.input_tokens += usage.input_tokens || 0;
          sendTurnUsage.output_tokens += usage.output_tokens || 0;
          sendTurnUsage.total_tokens += usage.total_tokens || 0;
          sendTurnUsage.cache_read_tokens += usage.cache_read_tokens || 0;
          sendTurnUsage.cache_creation_tokens += usage.cache_creation_tokens || 0;
          sendTurnUsage.calls += 1;
          if (usage.model) sendTurnUsage.model = usage.model;
          if (usage.provider) sendTurnUsage.provider = usage.provider;
          // Prefer streaming text (final response), then last TOOL_CALL (iteration cost),
          // then any assistant message. This keeps usage on TOOL_CALL so separators show per-call stats.
          const state = useConversationsStore.getState();
          const targetId =
            state.streamingTextId ??
            [...state.messages].reverse().find((m) => m.role === "assistant" && m.event_type === "TOOL_CALL")?.id ??
            [...state.messages].reverse().find((m) => m.role === "assistant")?.id;
          if (targetId) attachUsageToMessage(targetId, usage);
        } else if (event.event === "COMPLETE") {
          if (sendTurnUsage.calls > 0) setFinalMsgTurnUsage({ ...sendTurnUsage });
        } else {
          appendMessage({
            id: event.message_id,
            event_type: event.event,
            role: "assistant",
            payload: event.payload,
          });
        }
        result = await stream.next();
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        aborted = true;
        return;
      }
      appendMessage({
        id: uuidv4(),
        event_type: "ERROR",
        role: "assistant",
        payload: { error: String(err) },
      });
    } finally {
      streamAbortRef.current = null;
      finalizeStreaming();
      setStreaming(false);
      if (!aborted) {
        // Fire-and-forget title generation after the turn completes
        generateTitle(conversationId).then((r) => {
          if (r.updated) updateConversationTitle(conversationId, r.title);
        }).catch(() => {});
      }
    }
  };

  const handleWelcomeSend = async (text: string, engineName: string) => {
    pendingFirstMessage.current = text;
    const conv = await createConversation(engineName);
    addConversation(conv);
    setActiveId(conv.id);
  };

  if (!activeId) {
    return <WelcomeView onSend={handleWelcomeSend} />;
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden" data-print-chat>
      {/* Hidden print header — visible only when printing */}
      <div id="print-header" style={{ display: "none" }}>
        <h1 style={{ fontSize: "18px", fontWeight: 700, margin: 0 }}>
          {activeConv?.title ?? "Conversation"}
        </h1>
        <p style={{ fontSize: "12px", color: "#6b7280", margin: "4px 0 0" }}>
          Engine: {activeConv?.engine_name} · Exported {new Date().toLocaleString()}
        </p>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border" data-print-hide>
        <span className="text-sm font-medium truncate">
          {activeConv?.title ?? "Conversation"}
        </span>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <button
              onClick={() => setExportModalOpen(true)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground
                         px-2 py-1 rounded hover:bg-muted/60 transition-colors"
              title="Export as PDF"
            >
              <Download className="w-3.5 h-3.5" />
              Export PDF
            </button>
          )}
          <EngineSelector
            engines={engines}
            selected={activeConv?.engine_name ?? ""}
            onChange={async (name) => {
              if (!activeId || name === activeConv?.engine_name) return;
              await fetch(`/api/conversations/${activeId}/engine`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ engine_name: name }),
              });
              // Update local store
              useConversationsStore.setState((s) => ({
                conversations: s.conversations.map((c) =>
                  c.id === activeId ? { ...c, engine_name: name } : c
                ),
              }));
            }}
            disabled={isStreaming}
          />
        </div>
      </div>

      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        showReasoning={showReasoning}
        onChartError={(error) => {
          if (chartErrorRetried.current || isStreaming) return;
          chartErrorRetried.current = true;
          handleSend(
            `The chart failed to render with this error: "${error}". ` +
            `Please fix the Vega-Lite spec and regenerate the chart. ` +
            `Remember: use "mark": "bar" for horizontal bars — "barh" is not a valid Vega-Lite mark type.`
          );
        }}
      />
      <MessageInput
        onSend={handleSend}
        disabled={isStreaming}
        isStreaming={isStreaming}
        onStop={() => setStreaming(false)}
      />
      <ContextStatusBar
        conversationId={activeId}
        isStreaming={isStreaming}
        messageCount={messages.length}
      />

      {/* Export PDF modal */}
      {exportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setExportModalOpen(false)}>
          <div className="bg-background border border-border rounded-xl shadow-xl w-80 p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Export PDF</h2>
              <button onClick={() => setExportModalOpen(false)} className="text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <label className="flex items-center justify-between cursor-pointer">
                <span className="text-sm text-muted-foreground">Include reasoning</span>
                <button
                  onClick={() => {
                    const next = !exportIncludeReasoning;
                    setExportIncludeReasoning(next);
                    setShowReasoning(next);
                  }}
                  role="switch"
                  aria-checked={exportIncludeReasoning}
                  className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors duration-200 focus:outline-none ${
                    exportIncludeReasoning ? "bg-primary" : "bg-muted-foreground/30"
                  }`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200 mt-0.5 ${
                    exportIncludeReasoning ? "translate-x-4" : "translate-x-0.5"
                  }`} />
                </button>
              </label>
            </div>

            <button
              onClick={handleExport}
              className="w-full flex items-center justify-center gap-2 text-sm px-4 py-2 rounded-lg
                         bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <Download className="w-4 h-4" />
              Export
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
