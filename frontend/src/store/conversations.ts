import { create } from "zustand";
import type { ConversationSummary, Engine, UIMessage, UsagePayload } from "@/types";

export interface UsageTotals {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  calls: number;
}

const EMPTY_USAGE: UsageTotals = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_creation_tokens: 0,
  calls: 0,
};

interface ConversationsState {
  conversations: ConversationSummary[];
  activeId: string | null;
  messages: UIMessage[];
  engines: Engine[];
  isStreaming: boolean;
  // ID of the current turn's streaming TEXT message (reset each turn)
  streamingTextId: string | null;
  usageTotals: UsageTotals;

  setConversations: (list: ConversationSummary[]) => void;
  addConversation: (conv: ConversationSummary) => void;
  removeConversation: (id: string) => void;
  setActiveId: (id: string | null) => void;
  setMessages: (msgs: UIMessage[]) => void;
  appendMessage: (msg: UIMessage) => void;
  appendStreamingText: (text: string) => void;
  resetStreamingText: () => void;
  markCurrentAsThinking: () => void; // called when TOOL_CALL follows a TEXT block
  setEngines: (engines: Engine[]) => void;
  setStreaming: (v: boolean) => void;
  updateConversationTitle: (id: string, title: string) => void;
  setUsageTotals: (totals: UsageTotals) => void;
  addUsage: (usage: UsagePayload) => void;
  attachUsageToMessage: (messageId: string, usage: UsagePayload) => void;
  finalizeStreaming: () => void;
}

export const useConversationsStore = create<ConversationsState>((set) => ({
  conversations: [],
  activeId: null,
  messages: [],
  engines: [],
  isStreaming: false,
  streamingTextId: null,
  usageTotals: { ...EMPTY_USAGE },

  setConversations: (list) => set({ conversations: list }),
  addConversation: (conv) =>
    set((s) => ({ conversations: [conv, ...s.conversations] })),
  removeConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeId: s.activeId === id ? null : s.activeId,
    })),
  setActiveId: (id) =>
    set({ activeId: id, messages: [], streamingTextId: null, usageTotals: { ...EMPTY_USAGE } }),
  setMessages: (msgs) => set({ messages: msgs }),
  appendMessage: (msg) =>
    set((s) => ({ messages: [...s.messages, msg] })),

  // Append text to the current turn's TEXT message (creates it if needed)
  appendStreamingText: (text) =>
    set((s) => {
      if (s.streamingTextId) {
        // Update existing TEXT message for this turn
        const msgs = s.messages.map((m) =>
          m.id === s.streamingTextId
            ? { ...m, payload: { ...m.payload, text: (m.payload.text as string ?? "") + text } }
            : m
        );
        return { messages: msgs };
      }
      // Create a new TEXT message for this turn (isStreaming=true until marked as thinking or turn ends)
      const newId = crypto.randomUUID();
      return {
        streamingTextId: newId,
        messages: [
          ...s.messages,
          {
            id: newId,
            event_type: "TEXT" as const,
            role: "assistant" as const,
            payload: { text },
            isStreaming: true,
            isThinking: false,
          },
        ],
      };
    }),

  resetStreamingText: () => set({ streamingTextId: null }),

  markCurrentAsThinking: () =>
    set((s) => {
      if (!s.streamingTextId) return {};
      return {
        messages: s.messages.map((m) =>
          m.id === s.streamingTextId ? { ...m, isThinking: true, isStreaming: false } : m
        ),
        streamingTextId: null,
      };
    }),

  setEngines: (engines) => set({ engines }),
  setStreaming: (v) => set({ isStreaming: v }),
  updateConversationTitle: (id, title) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === id ? { ...c, title } : c
      ),
    })),

  setUsageTotals: (totals) => set({ usageTotals: totals }),
  attachUsageToMessage: (messageId, usage) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === messageId ? { ...m, usage } : m)),
    })),
  finalizeStreaming: () =>
    set((s) => ({
      messages: s.messages.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
      streamingTextId: null,
    })),
  addUsage: (usage) =>
    set((s) => ({
      usageTotals: {
        input_tokens: s.usageTotals.input_tokens + (usage.input_tokens || 0),
        output_tokens: s.usageTotals.output_tokens + (usage.output_tokens || 0),
        total_tokens: s.usageTotals.total_tokens + (usage.total_tokens || 0),
        cache_read_tokens:
          s.usageTotals.cache_read_tokens + (usage.cache_read_tokens || 0),
        cache_creation_tokens:
          s.usageTotals.cache_creation_tokens + (usage.cache_creation_tokens || 0),
        calls: s.usageTotals.calls + 1,
      },
    })),
}));
