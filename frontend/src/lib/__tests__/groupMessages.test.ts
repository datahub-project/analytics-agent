import { describe, it, expect } from "vitest";
import { groupIntoTurns, shouldShowSeparator, getSepUsage } from "../groupMessages";
import {v4 as uuidv4} from "uuid";
import type { UIMessage } from "@/types";

function msg(overrides: Partial<UIMessage> & Pick<UIMessage, "event_type" | "role">): UIMessage {
  return {
    id: overrides.id ?? uuidv4(),
    payload: overrides.payload ?? {},
    ...overrides,
  };
}

const userMsg = (id = "u1") => msg({ id, role: "user", event_type: "TEXT", payload: { text: "Q" } });
const toolCall = (id = "tc1", usage?: UIMessage["usage"]) =>
  msg({ id, role: "assistant", event_type: "TOOL_CALL", payload: { tool_name: "search", tool_input: {} }, usage });
const toolResult = (id = "tr1") =>
  msg({ id, role: "assistant", event_type: "TOOL_RESULT", payload: { tool_name: "search", result: "ok", is_error: false } });
const thinkingText = (id = "th1") =>
  msg({ id, role: "assistant", event_type: "TEXT", payload: { text: "thinking..." }, isThinking: true });
const finalText = (id = "ft1", streaming = false) =>
  msg({ id, role: "assistant", event_type: "TEXT", payload: { text: "Answer" }, isStreaming: streaming });

// ─── groupIntoTurns ──────────────────────────────────────────────────────────

describe("groupIntoTurns", () => {
  it("produces one group per user message", () => {
    const messages: UIMessage[] = [
      userMsg("u1"), finalText("f1"),
      userMsg("u2"), finalText("f2"),
    ];
    const groups = groupIntoTurns(messages, false);
    expect(groups).toHaveLength(2);
    expect(groups[0].userMsg!.id).toBe("u1");
    expect(groups[1].userMsg!.id).toBe("u2");
  });

  it("puts TOOL_CALL, TOOL_RESULT, isThinking TEXT in workMsgs", () => {
    const messages: UIMessage[] = [
      userMsg(),
      toolCall("tc"),
      toolResult("tr"),
      thinkingText("th"),
      finalText("ft"),
    ];
    const [group] = groupIntoTurns(messages, false);
    expect(group.workMsgs.map((m) => m.id)).toEqual(["tc", "tr", "th"]);
    expect(group.finalMsg!.id).toBe("ft");
  });

  it("simple Q&A (no tools) produces empty workMsgs", () => {
    const messages: UIMessage[] = [userMsg(), finalText()];
    const [group] = groupIntoTurns(messages, false);
    expect(group.workMsgs).toHaveLength(0);
    expect(group.finalMsg).toBeDefined();
  });

  it("sets isActivelyStreaming from finalMsg.isStreaming", () => {
    const messages: UIMessage[] = [userMsg(), toolCall(), toolResult(), finalText("ft", true)];
    const [group] = groupIntoTurns(messages, false);
    expect(group.isActivelyStreaming).toBe(true);
  });

  it("sets isActivelyStreaming from globalStreaming when no finalMsg yet", () => {
    const messages: UIMessage[] = [userMsg(), toolCall(), toolResult()];
    const [group] = groupIntoTurns(messages, true /* globalStreaming */);
    expect(group.isActivelyStreaming).toBe(true);
  });

  it("does not set isActivelyStreaming when globalStreaming=false and no streaming msg", () => {
    const messages: UIMessage[] = [userMsg(), toolCall(), toolResult(), finalText()];
    const [group] = groupIntoTurns(messages, false);
    expect(group.isActivelyStreaming).toBe(false);
  });

  it("uses the first user message id as the group key", () => {
    const messages: UIMessage[] = [userMsg("abc"), finalText()];
    const [group] = groupIntoTurns(messages, false);
    expect(group.key).toBe("abc");
  });
});

// ─── shouldShowSeparator ─────────────────────────────────────────────────────

describe("shouldShowSeparator", () => {
  it("returns false for the first TOOL_CALL (no preceding result)", () => {
    const msgs = [toolCall("tc1"), toolResult("tr1"), toolCall("tc2")];
    expect(shouldShowSeparator(msgs, 0)).toBe(false);
  });

  it("returns true before a TOOL_CALL that follows a TOOL_RESULT", () => {
    const msgs = [toolCall("tc1"), toolResult("tr1"), toolCall("tc2")];
    expect(shouldShowSeparator(msgs, 2)).toBe(true);
  });

  it("skips thinking blocks when looking backward", () => {
    // TOOL_RESULT → thinking TEXT → TOOL_CALL: separator should still show
    const msgs = [toolCall("tc1"), toolResult("tr1"), thinkingText("th"), toolCall("tc2")];
    expect(shouldShowSeparator(msgs, 3)).toBe(true);
  });

  it("returns false for non-TOOL_CALL messages", () => {
    const msgs = [toolCall("tc1"), toolResult("tr1")];
    expect(shouldShowSeparator(msgs, 1)).toBe(false);
  });

  it("returns false at index 0", () => {
    const msgs = [toolCall("tc1")];
    expect(shouldShowSeparator(msgs, 0)).toBe(false);
  });
});

// ─── getSepUsage ─────────────────────────────────────────────────────────────

describe("getSepUsage", () => {
  const u = { input_tokens: 5000, output_tokens: 80, total_tokens: 5080, cache_read_tokens: 0, cache_creation_tokens: 0, node: "t" };

  it("returns usage from the nearest preceding TOOL_CALL", () => {
    const msgs = [toolCall("tc1", u), toolResult("tr1"), toolCall("tc2")];
    expect(getSepUsage(msgs, 2)).toEqual(u);
  });

  it("skips non-TOOL_CALL messages when searching backward", () => {
    const msgs = [toolCall("tc1", u), toolResult("tr1"), thinkingText("th"), toolCall("tc2")];
    // Looking backward from idx=3 (tc2): th is not TOOL_CALL, tr1 is not, tc1 is
    expect(getSepUsage(msgs, 3)).toEqual(u);
  });

  it("returns undefined when no preceding TOOL_CALL exists", () => {
    const msgs = [toolResult("tr1"), toolCall("tc1")];
    // From idx=1, look back: tr1 is not TOOL_CALL → undefined
    expect(getSepUsage(msgs, 1)).toBeUndefined();
  });

  it("returns undefined for an empty preceding list", () => {
    const msgs = [toolCall("tc1")];
    expect(getSepUsage(msgs, 0)).toBeUndefined();
  });
});
