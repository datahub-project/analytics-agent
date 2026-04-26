import type { UIMessage, TurnUsage } from "@/types";

const WORK_TYPES = new Set(["TOOL_CALL", "TOOL_RESULT", "SQL", "CHART", "ERROR", "THINKING"]);

export interface TurnGroup {
  key: string;
  userMsg?: UIMessage;
  workMsgs: UIMessage[];
  finalMsg?: UIMessage;
  isActivelyStreaming: boolean;
}

export function groupIntoTurns(messages: UIMessage[], globalStreaming: boolean): TurnGroup[] {
  const groups: TurnGroup[] = [];
  let current: TurnGroup = { key: "init", workMsgs: [], isActivelyStreaming: false };

  for (const msg of messages) {
    if (msg.role === "user") {
      if (current.userMsg || current.workMsgs.length > 0 || current.finalMsg) {
        groups.push(current);
      }
      current = { key: msg.id, userMsg: msg, workMsgs: [], isActivelyStreaming: false };
      continue;
    }

    if (msg.event_type === "TEXT" && !msg.isThinking) {
      if (msg.isStreaming) current.isActivelyStreaming = true;
      current.finalMsg = msg;
    } else if (WORK_TYPES.has(msg.event_type) || (msg.event_type === "TEXT" && msg.isThinking)) {
      current.workMsgs.push(msg);
    }
  }

  if (current.userMsg || current.workMsgs.length > 0 || current.finalMsg) {
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
  for (let j = idx - 1; j >= 0; j--) {
    if (msgs[j].event_type === "TOOL_CALL") return msgs[j].usage;
  }
  return undefined;
}

// Re-export TurnUsage for convenience
export type { TurnUsage };
