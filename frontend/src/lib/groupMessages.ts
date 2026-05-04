import type { UIMessage, TurnUsage } from "@/types";

const WORK_TYPES = new Set(["TOOL_CALL", "TOOL_RESULT", "SQL", "ERROR", "THINKING"]);

export interface TurnGroup {
  key: string;
  userMsg?: UIMessage;
  workMsgs: UIMessage[];
  /** Chart events extracted from workMsgs — rendered outside the collapsible work block. */
  chartMsgs: UIMessage[];
  finalMsg?: UIMessage;
  isActivelyStreaming: boolean;
}

export function groupIntoTurns(messages: UIMessage[], globalStreaming: boolean): TurnGroup[] {
  const groups: TurnGroup[] = [];
  let current: TurnGroup = { key: "init", workMsgs: [], chartMsgs: [], isActivelyStreaming: false };

  for (const msg of messages) {
    if (msg.role === "user") {
      if (current.userMsg || current.workMsgs.length > 0 || current.chartMsgs.length > 0 || current.finalMsg) {
        groups.push(current);
      }
      current = { key: msg.id, userMsg: msg, workMsgs: [], chartMsgs: [], isActivelyStreaming: false };
      continue;
    }

    if (msg.event_type === "TEXT" && !msg.isThinking) {
      if (msg.isStreaming) current.isActivelyStreaming = true;
      current.finalMsg = msg;
    } else if (msg.event_type === "CHART") {
      // Charts rendered outside the collapsible work block so they stay visible when collapsed.
      current.chartMsgs.push(msg);
    } else if (WORK_TYPES.has(msg.event_type) || (msg.event_type === "TEXT" && msg.isThinking)) {
      current.workMsgs.push(msg);
    }
  }

  if (current.userMsg || current.workMsgs.length > 0 || current.chartMsgs.length > 0 || current.finalMsg) {
    if (globalStreaming && !current.finalMsg?.isStreaming) {
      current.isActivelyStreaming = globalStreaming;
    }
    groups.push(current);
  }

  return groups;
}

export function shouldShowSeparator(msgs: UIMessage[], idx: number): boolean {
  if (msgs[idx].event_type !== "TOOL_CALL") return false;
  for (let j = idx - 1; j >= 0; j--) {
    const et = msgs[j].event_type;
    if (et === "TEXT" && msgs[j].isThinking) continue;
    return ["TOOL_RESULT", "SQL", "CHART", "ERROR"].includes(et ?? "");
  }
  return false;
}

export function getSepUsage(msgs: UIMessage[], idx: number) {
  // Scan backward from the separator for the first message that carries usage.
  // Usage may land on TOOL_CALL or TOOL_RESULT depending on event ordering.
  for (let j = idx - 1; j >= 0; j--) {
    if (msgs[j].usage) return msgs[j].usage;
  }
  return undefined;
}

// Re-export TurnUsage for convenience
export type { TurnUsage };
