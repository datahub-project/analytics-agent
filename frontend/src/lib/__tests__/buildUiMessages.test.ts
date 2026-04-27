import { describe, it, expect } from "vitest";
import { buildUiMessages } from "../buildUiMessages";
import type { MessageRecord } from "@/types";

// Minimal factory so tests only specify what they care about
function rec(
  overrides: Partial<MessageRecord> & Pick<MessageRecord, "event_type" | "role">
): MessageRecord {
  return {
    id: overrides.id ?? crypto.randomUUID(),
    sequence: overrides.sequence ?? 0,
    created_at: overrides.created_at ?? "2024-01-01T00:00:00Z",
    payload: overrides.payload ?? {},
    ...overrides,
  };
}

function usage(input: number, output: number) {
  return { input_tokens: input, output_tokens: output, total_tokens: input + output, cache_read_tokens: 0, cache_creation_tokens: 0, node: "test" };
}

// ─── Simple Q&A (no tools) ───────────────────────────────────────────────────

describe("simple Q&A turn", () => {
  it("merges streaming TEXT chunks into a single bubble", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Hello" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Hi " } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "there!" } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe("user");
    expect(messages[1].role).toBe("assistant");
    expect(messages[1].event_type).toBe("TEXT");
    expect((messages[1].payload as { text: string }).text).toBe("Hi there!");
    expect(messages[1].isThinking).toBe(false);
  });

  it("COMPLETE text supersedes merged chunks when non-empty", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "partial..." } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "Final answer." } }),
    ];

    const { messages } = buildUiMessages(records);
    expect((messages[1].payload as { text: string }).text).toBe("Final answer.");
  });

  it("falls back to merged chunks when COMPLETE text is empty", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Answer" } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    expect((messages[1].payload as { text: string }).text).toBe("Answer");
  });

  it("attaches turnUsage to the final TEXT when USAGE events are present", () => {
    const u = usage(1000, 50);
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "A" } }),
      rec({ role: "assistant", event_type: "USAGE", payload: u as never }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    const finalMsg = messages[1];
    expect(finalMsg.turnUsage).toBeDefined();
    expect(finalMsg.turnUsage!.input_tokens).toBe(1000);
    expect(finalMsg.turnUsage!.output_tokens).toBe(50);
    expect(finalMsg.turnUsage!.calls).toBe(1);
  });

  it("accumulates totals across USAGE events", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "USAGE", payload: usage(500, 20) as never }),
      rec({ role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "search", tool_input: {} } }),
      rec({ role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: "search", result: "ok", is_error: false } }),
      rec({ role: "assistant", event_type: "USAGE", payload: usage(800, 30) as never }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Done." } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { totals } = buildUiMessages(records);
    expect(totals.input_tokens).toBe(1300);
    expect(totals.output_tokens).toBe(50);
    expect(totals.calls).toBe(2);
  });
});

// ─── Tool-calling turn ───────────────────────────────────────────────────────

describe("tool-calling turn", () => {
  it("marks TEXT before a TOOL_CALL as isThinking", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Let me check..." } }),
      rec({ role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "search", tool_input: {} } }),
      rec({ role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: "search", result: "results", is_error: false } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Here you go." } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    const thinkingMsg = messages.find((m) => m.isThinking);
    expect(thinkingMsg).toBeDefined();
    expect((thinkingMsg!.payload as { text: string }).text).toBe("Let me check...");

    const finalMsg = messages.find((m) => m.event_type === "TEXT" && !m.isThinking && m.role === "assistant");
    expect(finalMsg).toBeDefined();
    expect((finalMsg!.payload as { text: string }).text).toBe("Here you go.");
  });

  it("attaches USAGE to the previous TOOL_CALL in result", () => {
    const u = usage(8000, 60);
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "t1", tool_input: {} } }),
      rec({ role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: "t1", result: "r1", is_error: false } }),
      rec({ role: "assistant", event_type: "USAGE", payload: u as never }),
      rec({ role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "t2", tool_input: {} } }),
      rec({ role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: "t2", result: "r2", is_error: false } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Done." } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    const tc1 = messages.find((m) => m.event_type === "TOOL_CALL" && (m.payload as { tool_name: string }).tool_name === "t1");
    expect(tc1!.usage).toEqual(expect.objectContaining({ input_tokens: 8000 }));
  });

  it("emits SQL and CHART messages directly (no merging)", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "execute_sql", tool_input: {} } }),
      rec({ role: "assistant", event_type: "SQL", payload: { sql: "SELECT 1", columns: [], rows: [], truncated: false } }),
      rec({ role: "assistant", event_type: "CHART", payload: { vega_lite_spec: {}, reasoning: "", chart_type: "bar" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "Here is your chart." } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    expect(messages.some((m) => m.event_type === "SQL")).toBe(true);
    expect(messages.some((m) => m.event_type === "CHART")).toBe(true);
  });
});

// ─── Multi-turn conversation ──────────────────────────────────────────────────

describe("multi-turn conversation", () => {
  it("resets turnUsage accumulation per user message", () => {
    const records: MessageRecord[] = [
      // Turn 1
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q1" } }),
      rec({ role: "assistant", event_type: "USAGE", payload: usage(100, 10) as never }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "A1" } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
      // Turn 2
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q2" } }),
      rec({ role: "assistant", event_type: "USAGE", payload: usage(200, 20) as never }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "A2" } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    const a1 = messages.find((m) => m.role === "assistant" && (m.payload as { text: string }).text === "A1");
    const a2 = messages.find((m) => m.role === "assistant" && (m.payload as { text: string }).text === "A2");

    expect(a1!.turnUsage!.input_tokens).toBe(100);
    expect(a2!.turnUsage!.input_tokens).toBe(200);
  });

  it("drops whitespace-only TEXT messages", () => {
    const records: MessageRecord[] = [
      rec({ role: "user", event_type: "TEXT", payload: { text: "Q" } }),
      rec({ role: "assistant", event_type: "TEXT", payload: { text: "   " } }),
      rec({ role: "assistant", event_type: "COMPLETE", payload: { text: "" } }),
    ];

    const { messages } = buildUiMessages(records);
    // Only the user message; empty-text assistant bubble is suppressed
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("user");
  });
});
