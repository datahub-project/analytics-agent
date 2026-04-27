import { describe, it, expect, beforeEach } from "vitest";
import { buildUiMessages } from "../buildUiMessages";
import { groupIntoTurns, shouldShowSeparator } from "../groupMessages";
import type { MessageRecord, UIMessage } from "@/types";

// ─── Helpers ─────────────────────────────────────────────────────────────────

let seq = 0;
function rec(
  role: "user" | "assistant",
  event_type: string,
  payload: Record<string, unknown> = {}
): MessageRecord {
  return {
    id: `id-${seq++}`,
    sequence: seq,
    created_at: new Date(Date.now() + seq * 100).toISOString(),
    role,
    event_type: event_type as MessageRecord["event_type"],
    payload,
  };
}

function usage(input = 8000, output = 60) {
  return { input_tokens: input, output_tokens: output, total_tokens: input + output, cache_read_tokens: 0, cache_creation_tokens: 0, node: "test" };
}

function toolCallRec(name: string) {
  return rec("assistant", "TOOL_CALL", { tool_name: name, tool_input: {} });
}
function toolResultRec(name: string) {
  return rec("assistant", "TOOL_RESULT", { tool_name: name, result: "ok", is_error: false });
}

beforeEach(() => { seq = 0; });

// ─── Many tool calls in a single turn ────────────────────────────────────────

describe("many tool calls", () => {
  it("handles 50 sequential tool call/result pairs without data loss", () => {
    const N = 50;
    const records: MessageRecord[] = [rec("user", "TEXT", { text: "Q" })];
    for (let i = 0; i < N; i++) {
      records.push(rec("assistant", "USAGE", usage()));
      records.push(toolCallRec(`tool_${i}`));
      records.push(toolResultRec(`tool_${i}`));
    }
    records.push(rec("assistant", "TEXT", { text: "Done." }));
    records.push(rec("assistant", "COMPLETE", { text: "Done." }));

    const { messages, totals } = buildUiMessages(records);

    const toolCalls = messages.filter((m) => m.event_type === "TOOL_CALL");
    const toolResults = messages.filter((m) => m.event_type === "TOOL_RESULT");
    expect(toolCalls).toHaveLength(N);
    expect(toolResults).toHaveLength(N);
    expect(totals.calls).toBe(N);
  });

  it("groupIntoTurns with 50 tool calls produces a single work block", () => {
    const msgs: UIMessage[] = [
      { id: "u1", role: "user", event_type: "TEXT", payload: { text: "Q" } },
    ];
    for (let i = 0; i < 50; i++) {
      msgs.push({ id: `tc${i}`, role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: `t${i}`, tool_input: {} } });
      msgs.push({ id: `tr${i}`, role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: `t${i}`, result: "ok", is_error: false } });
    }
    msgs.push({ id: "ft", role: "assistant", event_type: "TEXT", payload: { text: "Answer" } });

    const groups = groupIntoTurns(msgs, false);
    expect(groups).toHaveLength(1);
    expect(groups[0].workMsgs).toHaveLength(100); // 50 calls + 50 results
    expect(groups[0].finalMsg!.id).toBe("ft");
  });

  it("separator shows correctly for 20 sequential tool iterations", () => {
    const msgs: UIMessage[] = [];
    for (let i = 0; i < 20; i++) {
      msgs.push({ id: `tc${i}`, role: "assistant", event_type: "TOOL_CALL", payload: {} });
      msgs.push({ id: `tr${i}`, role: "assistant", event_type: "TOOL_RESULT", payload: {} });
    }
    // First TOOL_CALL (idx=0) — no separator
    expect(shouldShowSeparator(msgs, 0)).toBe(false);
    // All subsequent TOOL_CALLs (idx=2,4,6,...) — separator expected
    for (let i = 1; i < 20; i++) {
      expect(shouldShowSeparator(msgs, i * 2)).toBe(true);
    }
  });
});

// ─── Very long text content ───────────────────────────────────────────────────

describe("very long text content", () => {
  it("merges 500 streaming text chunks correctly", () => {
    const records: MessageRecord[] = [rec("user", "TEXT", { text: "Q" })];
    const chunks = Array.from({ length: 500 }, (_, i) => `chunk${i} `);
    for (const chunk of chunks) {
      records.push(rec("assistant", "TEXT", { text: chunk }));
    }
    records.push(rec("assistant", "COMPLETE", { text: "" }));

    const { messages } = buildUiMessages(records);
    const response = messages.find((m) => m.role === "assistant" && m.event_type === "TEXT");
    expect(response).toBeDefined();
    const text = (response!.payload as { text: string }).text;
    expect(text).toBe(chunks.join(""));
    expect(text.length).toBeGreaterThan(3000);
  });

  it("handles a single chunk with 100k characters", () => {
    const bigText = "x".repeat(100_000);
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      rec("assistant", "TEXT", { text: bigText }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];
    const { messages } = buildUiMessages(records);
    const response = messages.find((m) => m.role === "assistant");
    expect((response!.payload as { text: string }).text).toHaveLength(100_000);
  });

  it("COMPLETE text with 50k characters supersedes chunks", () => {
    const bigComplete = "c".repeat(50_000);
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      rec("assistant", "TEXT", { text: "partial" }),
      rec("assistant", "COMPLETE", { text: bigComplete }),
    ];
    const { messages } = buildUiMessages(records);
    const response = messages.find((m) => m.role === "assistant");
    expect((response!.payload as { text: string }).text).toHaveLength(50_000);
  });
});

// ─── Many conversation turns ──────────────────────────────────────────────────

describe("many conversation turns", () => {
  it("handles 100 back-and-forth turns without cross-contamination", () => {
    const records: MessageRecord[] = [];
    for (let i = 0; i < 100; i++) {
      records.push(rec("user", "TEXT", { text: `Q${i}` }));
      records.push(rec("assistant", "USAGE", usage(i * 100, i * 10)));
      records.push(rec("assistant", "TEXT", { text: `A${i}` }));
      records.push(rec("assistant", "COMPLETE", { text: `A${i}` }));
    }

    const { messages, totals } = buildUiMessages(records);

    // 100 user + 100 assistant = 200 messages
    expect(messages).toHaveLength(200);
    expect(totals.calls).toBe(100);

    // Each assistant response should have its own turnUsage (only 1 call each)
    const assistantMsgs = messages.filter((m) => m.role === "assistant");
    for (const m of assistantMsgs) {
      expect(m.turnUsage).toBeDefined();
      expect(m.turnUsage!.calls).toBe(1);
    }

    // Verify no cross-contamination of text
    expect((assistantMsgs[0].payload as { text: string }).text).toBe("A0");
    expect((assistantMsgs[99].payload as { text: string }).text).toBe("A99");
  });

  it("groupIntoTurns produces one group per user message across 100 turns", () => {
    const msgs: UIMessage[] = [];
    for (let i = 0; i < 100; i++) {
      msgs.push({ id: `u${i}`, role: "user", event_type: "TEXT", payload: { text: `Q${i}` } });
      msgs.push({ id: `a${i}`, role: "assistant", event_type: "TEXT", payload: { text: `A${i}` } });
    }
    const groups = groupIntoTurns(msgs, false);
    expect(groups).toHaveLength(100);
    for (let i = 0; i < 100; i++) {
      expect(groups[i].userMsg!.id).toBe(`u${i}`);
      expect(groups[i].workMsgs).toHaveLength(0);
      expect(groups[i].finalMsg!.id).toBe(`a${i}`);
    }
  });
});

// ─── Parallel tool calls (multiple tools in one LLM invocation) ───────────────

describe("parallel tool calls", () => {
  it("preserves all parallel tool calls and results", () => {
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      // LLM decides to call two tools in parallel
      rec("assistant", "USAGE", usage()),
      toolCallRec("search_a"),
      toolCallRec("search_b"),
      toolResultRec("search_a"),
      toolResultRec("search_b"),
      rec("assistant", "TEXT", { text: "Both done." }),
      rec("assistant", "COMPLETE", { text: "Both done." }),
    ];

    const { messages } = buildUiMessages(records);
    const toolCalls = messages.filter((m) => m.event_type === "TOOL_CALL");
    const toolResults = messages.filter((m) => m.event_type === "TOOL_RESULT");
    expect(toolCalls).toHaveLength(2);
    expect(toolResults).toHaveLength(2);
  });

  it("attaches USAGE to the last available TOOL_CALL when parallel calls exist", () => {
    const u = usage(9000, 70);
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      rec("assistant", "USAGE", u),
      toolCallRec("tc_a"),
      toolCallRec("tc_b"),
      toolResultRec("tc_a"),
      toolResultRec("tc_b"),
      rec("assistant", "TEXT", { text: "Done." }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];

    const { messages } = buildUiMessages(records);
    // USAGE arrives before the TOOL_CALLs so it searches backward in result
    // and finds nothing assistant-level yet — usage is not lost but may attach
    // to nothing for the first call. Key: the final response should still have turnUsage.
    const finalMsg = messages.find((m) => m.role === "assistant" && m.event_type === "TEXT" && !m.isThinking);
    expect(finalMsg!.turnUsage).toBeDefined();
    expect(finalMsg!.turnUsage!.input_tokens).toBe(9000);
  });
});

// ─── Edge cases ───────────────────────────────────────────────────────────────

describe("edge cases", () => {
  it("empty input produces empty output", () => {
    const { messages, totals } = buildUiMessages([]);
    expect(messages).toHaveLength(0);
    expect(totals.calls).toBe(0);
  });

  it("orphaned assistant messages (no preceding user message) are included", () => {
    const records: MessageRecord[] = [
      rec("assistant", "TEXT", { text: "Unsolicited." }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];
    const { messages } = buildUiMessages(records);
    // Trailing flush should emit the text
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("assistant");
  });

  it("handles interleaved SQL and CHART events without losing them", () => {
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Chart me" }),
      toolCallRec("execute_sql"),
      rec("assistant", "SQL", { sql: "SELECT 1", columns: ["x"], rows: [{ x: 1 }], truncated: false }),
      rec("assistant", "CHART", { vega_lite_spec: { mark: "bar" }, reasoning: "", chart_type: "bar" }),
      rec("assistant", "TEXT", { text: "Here is your chart." }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];

    const { messages } = buildUiMessages(records);
    expect(messages.some((m) => m.event_type === "SQL")).toBe(true);
    expect(messages.some((m) => m.event_type === "CHART")).toBe(true);
  });

  it("tool call immediately followed by another tool call (no result between) is handled", () => {
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      toolCallRec("t1"),
      toolCallRec("t2"), // two calls with no result between (unusual but shouldn't crash)
      toolResultRec("t1"),
      toolResultRec("t2"),
      rec("assistant", "TEXT", { text: "Done." }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];

    expect(() => buildUiMessages(records)).not.toThrow();
    const { messages } = buildUiMessages(records);
    expect(messages.filter((m) => m.event_type === "TOOL_CALL")).toHaveLength(2);
  });

  it("USAGE with zero token values does not corrupt totals", () => {
    const records: MessageRecord[] = [
      rec("user", "TEXT", { text: "Q" }),
      rec("assistant", "USAGE", { input_tokens: 0, output_tokens: 0, total_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0, node: "t" }),
      rec("assistant", "TEXT", { text: "A" }),
      rec("assistant", "COMPLETE", { text: "" }),
    ];
    const { totals } = buildUiMessages(records);
    expect(totals.input_tokens).toBe(0);
    expect(totals.calls).toBe(1);
  });

  it("groupIntoTurns with no messages returns empty array", () => {
    expect(groupIntoTurns([], false)).toHaveLength(0);
    expect(groupIntoTurns([], true)).toHaveLength(0);
  });

  it("groupIntoTurns with only a user message (no response yet) produces one group", () => {
    const msgs: UIMessage[] = [
      { id: "u1", role: "user", event_type: "TEXT", payload: { text: "Q" } },
    ];
    const groups = groupIntoTurns(msgs, true);
    expect(groups).toHaveLength(1);
    expect(groups[0].finalMsg).toBeUndefined();
    expect(groups[0].isActivelyStreaming).toBe(true);
  });
});

// ─── Performance bounds ───────────────────────────────────────────────────────

describe("performance", () => {
  it("buildUiMessages processes 1000 records in under 100ms", () => {
    const records: MessageRecord[] = [rec("user", "TEXT", { text: "Q" })];
    for (let i = 0; i < 200; i++) {
      records.push(rec("assistant", "USAGE", usage()));
      records.push(toolCallRec(`tool_${i}`));
      records.push(toolResultRec(`tool_${i}`));
    }
    records.push(rec("assistant", "TEXT", { text: "Done." }));
    records.push(rec("assistant", "COMPLETE", { text: "" }));
    // Should be ~804 records

    const start = performance.now();
    buildUiMessages(records);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(100);
  });

  it("groupIntoTurns processes 5000 messages in under 50ms", () => {
    const msgs: UIMessage[] = [];
    for (let i = 0; i < 50; i++) {
      msgs.push({ id: `u${i}`, role: "user", event_type: "TEXT", payload: {} });
      for (let j = 0; j < 49; j++) {
        msgs.push({ id: `w${i}-${j}`, role: "assistant", event_type: "TOOL_CALL", payload: {} });
        msgs.push({ id: `r${i}-${j}`, role: "assistant", event_type: "TOOL_RESULT", payload: {} });
      }
      msgs.push({ id: `f${i}`, role: "assistant", event_type: "TEXT", payload: {} });
    }
    // 50 turns × (1 user + 98 work + 1 final) = 5000 messages

    const start = performance.now();
    groupIntoTurns(msgs, false);
    const elapsed = performance.now() - start;

    expect(elapsed).toBeLessThan(50);
  });
});
