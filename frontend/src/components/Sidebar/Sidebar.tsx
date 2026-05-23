import { useState } from "react";
import { Plus, Search } from "lucide-react";
import { useConversationsStore } from "@/store/conversations";
import { createConversation, deleteConversation } from "@/api/conversations";
import { ConversationItem } from "./ConversationItem";
import { AppLogo } from "@/components/Brand/AppLogo";
import { DataHubBadge } from "@/components/Brand/DataHubBadge";
import { ThemeSwitcher } from "@/components/Brand/ThemeSwitcher";

export function Sidebar() {
  const {
    conversations,
    activeId,
    engines,
    setActiveId,
    addConversation,
    removeConversation,
  } = useConversationsStore();

  const [filter, setFilter] = useState("");

  const defaultEngine = engines[0]?.name ?? "";

  const handleNew = async () => {
    const conv = await createConversation(defaultEngine);
    addConversation(conv);
    setActiveId(conv.id);
    setFilter("");
  };

  const handleDelete = async (id: string) => {
    await deleteConversation(id);
    removeConversation(id);
  };

  const normalizedFilter = filter.trim().toLowerCase();
  const visibleConversations = normalizedFilter
    ? conversations.filter((c) =>
        c.title.toLowerCase().includes(normalizedFilter)
      )
    : conversations;

  return (
    <aside className="w-64 flex flex-col border-r border-border h-full bg-muted/40">
      {/* Brand header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border">
        <button
          onClick={() => setActiveId(null)}
          className="hover:opacity-70 transition-opacity"
          title="Home"
        >
          <AppLogo />
        </button>
        <button
          onClick={handleNew}
          className="p-1.5 rounded-md hover:bg-muted transition-colors"
          title="New conversation"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* Filter */}
      <div className="px-3 py-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter conversations…"
            className="w-full pl-7 pr-2 py-1.5 text-xs bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/40"
          />
        </div>
      </div>

      {/* Conversations */}
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {conversations.length === 0 ? (
          <p className="text-xs text-muted-foreground px-2 py-4 text-center">
            No conversations yet
          </p>
        ) : visibleConversations.length === 0 ? (
          <p className="text-xs text-muted-foreground px-2 py-4 text-center">
            No matching conversations
          </p>
        ) : (
          visibleConversations.map((conv) => (
            <ConversationItem
              key={conv.id}
              conversation={conv}
              isActive={conv.id === activeId}
              onSelect={() => setActiveId(conv.id)}
              onDelete={() => handleDelete(conv.id)}
            />
          ))
        )}
      </div>

      {/* Footer: theme switcher + DataHub badge */}
      <div className="px-3 py-3 border-t border-border flex items-center justify-between">
        <DataHubBadge />
        <ThemeSwitcher />
      </div>
    </aside>
  );
}
