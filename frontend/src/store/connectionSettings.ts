import { create } from "zustand";
import { saveToolToggles, type Connection } from "@/api/settings";
import { listEngines } from "@/api/conversations";
import { useConversationsStore } from "@/store/conversations";

interface ConnectionSettingsState {
  disabledTools: string[];
  enabledMutations: string[];
  disabledConnections: string[];
  saving: boolean;

  // Derived helpers (avoid re-creating Sets on every call site)
  isToolDisabled: (name: string) => boolean;
  isMutationEnabled: (name: string) => boolean;
  isConnectionDisabled: (name: string) => boolean;

  // Called once on modal open to hydrate from the API response
  initialize: (connections: Connection[]) => void;

  // Atomic toggle actions — each patches state and persists in one call
  toggleTool: (name: string, currentlyEnabled: boolean) => Promise<void>;
  toggleMutation: (name: string, currentlyEnabled: boolean) => Promise<void>;
  toggleConnection: (name: string, enable: boolean) => Promise<void>;
}

export const useConnectionSettingsStore = create<ConnectionSettingsState>((set, get) => ({
  disabledTools: [],
  enabledMutations: [],
  disabledConnections: [],
  saving: false,

  isToolDisabled: (name) => get().disabledTools.includes(name),
  isMutationEnabled: (name) => get().enabledMutations.includes(name),
  isConnectionDisabled: (name) => get().disabledConnections.includes(name),

  initialize: (connections) => {
    const disabledTools: string[] = [];
    const enabledMutations: string[] = [];
    const disabledConnections: string[] = [];
    const MUTATION_NAMES = new Set(["publish_analysis", "save_correction"]);

    const CONTEXT_PLATFORM_TYPES = new Set(["datahub", "datahub-mcp"]);
    for (const conn of connections) {
      if (conn.disabled) disabledConnections.push(conn.name);
      for (const tool of conn.tools ?? []) {
        if (MUTATION_NAMES.has(tool.name)) {
          // Mutation tools are always global regardless of connection type
          if (tool.enabled) enabledMutations.push(tool.name);
        } else if (!CONTEXT_PLATFORM_TYPES.has(conn.type)) {
          // Non-mutation engine tools use the global disabledTools store.
          // DataHub read tools are managed per-connection — exclude from global store.
          if (!tool.enabled) disabledTools.push(tool.name);
        }
      }
    }
    // Deduplicate (multiple connections may expose the same tool name)
    set({
      disabledTools: [...new Set(disabledTools)],
      enabledMutations: [...new Set(enabledMutations)],
      disabledConnections: [...new Set(disabledConnections)],
    });
  },

  toggleTool: async (name, currentlyEnabled) => {
    const { disabledTools, enabledMutations, disabledConnections } = get();
    const next = currentlyEnabled
      ? [...disabledTools, name]
      : disabledTools.filter((n) => n !== name);
    set({ disabledTools: next, saving: true });
    try {
      await saveToolToggles(next, enabledMutations, disabledConnections);
    } finally {
      set({ saving: false });
    }
  },

  toggleMutation: async (name, currentlyEnabled) => {
    const { disabledTools, enabledMutations, disabledConnections } = get();
    const next = currentlyEnabled
      ? enabledMutations.filter((n) => n !== name)
      : [...enabledMutations, name];
    set({ enabledMutations: next, saving: true });
    try {
      await saveToolToggles(disabledTools, next, disabledConnections);
    } finally {
      set({ saving: false });
    }
  },

  toggleConnection: async (name, enable) => {
    const { disabledTools, enabledMutations, disabledConnections } = get();
    const next = enable
      ? disabledConnections.filter((n) => n !== name)
      : [...disabledConnections, name];
    set({ disabledConnections: next, saving: true });
    try {
      await saveToolToggles(disabledTools, enabledMutations, next);
      // Refresh engine dropdown so it only shows enabled data sources.
      const engines = await listEngines();
      useConversationsStore.getState().setEngines(engines);
    } finally {
      set({ saving: false });
    }
  },
}));
