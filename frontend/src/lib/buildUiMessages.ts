import type { MessageRecord, UIMessage, UsagePayload, TurnUsage } from "@/types";

export function buildUiMessages(records: MessageRecord[]): {
  messages: UIMessage[];
  totals: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cache_read_tokens: number;
    cache_creation_tokens: number;
    calls: number;
  };
} {
  const result: UIMessage[] = [];
  const totals = {
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    calls: 0,
  };

  let pendingTextChunks: { id: string; text: string; created_at?: string }[] = [];
  let completeText = "";
  let seenToolCallAfterText = false;
  let turnUsages: UsagePayload[] = [];
  // USAGE arrives at on_chat_model_end — BEFORE the next TOOL_CALL or COMPLETE
  // flushes the pending text. Stash it here and attach to the message pushed by
  // the next flushText() call (the thinking/response from the same LLM call).
  let pendingUsage: UsagePayload | null = null;

  const flushText = (asThinking: boolean) => {
    if (pendingTextChunks.length === 0) return;
    const merged = pendingTextChunks.map((c) => c.text).join("");
    const finalText = !asThinking && completeText ? completeText : merged;
    if (finalText.trim()) {
      const msg: UIMessage = {
        id: pendingTextChunks[0].id,
        event_type: "TEXT",
        role: "assistant",
        payload: { text: finalText },
        isThinking: asThinking,
        created_at: pendingTextChunks[0].created_at,
      };
      if (pendingUsage) {
        msg.usage = pendingUsage;
        pendingUsage = null;
      }
      result.push(msg);
    }
    pendingTextChunks = [];
    completeText = "";
    seenToolCallAfterText = false;
  };

  for (const m of records) {
    if (m.role === "user") {
      flushText(seenToolCallAfterText);
      turnUsages = [];
      result.push({ id: m.id, event_type: m.event_type, role: "user", payload: m.payload, created_at: m.created_at });
      continue;
    }

    switch (m.event_type) {
      case "TEXT":
        pendingTextChunks.push({ id: m.id, text: (m.payload.text as string) || "", created_at: m.created_at });
        break;

      case "COMPLETE":
        completeText = (m.payload.text as string) || "";
        flushText(false);
        if (turnUsages.length > 0 && result.length > 0) {
          const last = result[result.length - 1];
          if (last.role === "assistant" && last.event_type === "TEXT" && !last.isThinking) {
            const tu: TurnUsage = {
              input_tokens: 0, output_tokens: 0, total_tokens: 0,
              cache_read_tokens: 0, cache_creation_tokens: 0,
              calls: turnUsages.length,
            };
            for (const u of turnUsages) {
              tu.input_tokens += u.input_tokens || 0;
              tu.output_tokens += u.output_tokens || 0;
              tu.total_tokens += u.total_tokens || 0;
              tu.cache_read_tokens += u.cache_read_tokens || 0;
              tu.cache_creation_tokens += u.cache_creation_tokens || 0;
            }
            last.turnUsage = tu;
          }
        }
        turnUsages = [];
        break;

      case "TOOL_CALL":
        flushText(true);
        seenToolCallAfterText = true;
        result.push({ id: m.id, event_type: "TOOL_CALL", role: "assistant", payload: m.payload, created_at: m.created_at });
        break;

      case "TOOL_RESULT":
      case "SQL":
      case "CHART":
      case "ERROR":
        result.push({ id: m.id, event_type: m.event_type, role: "assistant", payload: m.payload, created_at: m.created_at });
        break;

      case "USAGE": {
        const u = m.payload as unknown as UsagePayload;
        totals.input_tokens += u.input_tokens || 0;
        totals.output_tokens += u.output_tokens || 0;
        totals.total_tokens += u.total_tokens || 0;
        totals.cache_read_tokens += u.cache_read_tokens || 0;
        totals.cache_creation_tokens += u.cache_creation_tokens || 0;
        totals.calls += 1;
        turnUsages.push(u);
        // If we have buffered TEXT chunks, the USAGE belongs to them — they'll
        // be flushed as a thinking/response message on the next TOOL_CALL or
        // COMPLETE. Stash and attach at flush time.
        if (pendingTextChunks.length > 0) {
          pendingUsage = u;
          break;
        }
        // No pending text — this LLM call produced only tool calls. Walk back
        // within the current call's slice (stop at TOOL_RESULT/SQL/CHART/ERROR)
        // and attach to the most recent TOOL_CALL.
        for (let j = result.length - 1; j >= 0; j--) {
          const r = result[j];
          if (r.role !== "assistant") continue;
          if (r.event_type === "TOOL_CALL") {
            r.usage = u;
            break;
          }
          if (
            r.event_type === "TOOL_RESULT" ||
            r.event_type === "SQL" ||
            r.event_type === "CHART" ||
            r.event_type === "ERROR"
          ) {
            break;
          }
        }
        break;
      }

      default:
        break;
    }
  }

  flushText(seenToolCallAfterText);
  return { messages: result, totals };
}
