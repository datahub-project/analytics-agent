import { Trash2 } from "lucide-react";
import type { ConversationSummary } from "@/types";

interface Props {
  conversation: ConversationSummary;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

export function ConversationItem({ conversation, isActive, onSelect, onDelete }: Props) {
  return (
    <div
      className={`group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer transition-colors ${
        isActive
          ? "bg-secondary text-secondary-foreground"
          : "hover:bg-muted text-foreground"
      }`}
      data-testid="conversation-item"
      data-conv-id={conversation.id}
      onClick={onSelect}
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate">{conversation.title}</p>
        <p className="text-xs text-muted-foreground">{conversation.engine_name}</p>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="opacity-0 group-hover:opacity-100 p-1 rounded hover:text-red-500 transition-all"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
