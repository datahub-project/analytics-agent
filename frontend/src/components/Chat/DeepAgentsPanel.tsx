import { useState } from "react";
import { Check, Circle, CircleDot, FileText, ListTodo, X } from "lucide-react";
import { useConversationsStore } from "@/store/conversations";
import type { TodoItem } from "@/types";

type Tab = "plan" | "files";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function DeepAgentsPanel({ open, onClose }: Props) {
  const todos = useConversationsStore((s) => s.todos);
  const files = useConversationsStore((s) => s.files);
  const [tab, setTab] = useState<Tab>("plan");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  if (!open) return null;

  const fileEntries = Object.entries(files);

  return (
    <aside className="w-80 flex-shrink-0 border-l border-border bg-background flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex gap-1">
          <button
            onClick={() => setTab("plan")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors
              ${tab === "plan" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"}`}
          >
            <ListTodo className="w-3.5 h-3.5" />
            Plan
            {todos.length > 0 && (
              <span className="ml-1 px-1.5 rounded-full bg-muted text-[10px]">
                {todos.filter((t) => t.status === "completed").length}/{todos.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab("files")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors
              ${tab === "files" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"}`}
          >
            <FileText className="w-3.5 h-3.5" />
            Files
            {fileEntries.length > 0 && (
              <span className="ml-1 px-1.5 rounded-full bg-muted text-[10px]">
                {fileEntries.length}
              </span>
            )}
          </button>
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors p-1"
          aria-label="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "plan" ? <PlanTab todos={todos} /> : (
          <FilesTab
            files={files}
            selected={selectedFile}
            onSelect={setSelectedFile}
          />
        )}
      </div>
    </aside>
  );
}

function PlanTab({ todos }: { todos: TodoItem[] }) {
  if (todos.length === 0) {
    return (
      <div className="p-4 text-xs text-muted-foreground/70">
        The agent's plan will appear here when it calls <code className="font-mono">write_todos</code>.
      </div>
    );
  }
  return (
    <ul className="p-3 space-y-1.5">
      {todos.map((t, i) => (
        <li key={i} className="flex items-start gap-2 text-xs">
          <span className="mt-0.5 flex-shrink-0">
            {t.status === "completed" ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" strokeWidth={3} />
            ) : t.status === "in_progress" ? (
              <CircleDot className="w-3.5 h-3.5 text-primary animate-pulse" />
            ) : (
              <Circle className="w-3.5 h-3.5 text-muted-foreground/40" />
            )}
          </span>
          <span className={
            t.status === "completed"
              ? "line-through text-muted-foreground/60"
              : t.status === "in_progress"
              ? "text-foreground font-medium"
              : "text-foreground/80"
          }>
            {t.status === "in_progress" && t.activeForm ? t.activeForm : t.content}
          </span>
        </li>
      ))}
    </ul>
  );
}

function FilesTab({
  files,
  selected,
  onSelect,
}: {
  files: Record<string, string>;
  selected: string | null;
  onSelect: (path: string | null) => void;
}) {
  const entries = Object.entries(files);
  if (entries.length === 0) {
    return (
      <div className="p-4 text-xs text-muted-foreground/70">
        The agent's virtual filesystem will appear here when it calls{" "}
        <code className="font-mono">write_file</code> or <code className="font-mono">edit_file</code>.
      </div>
    );
  }
  if (selected && files[selected] !== undefined) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between px-3 py-2 border-b border-border">
          <code className="text-xs font-mono truncate">{selected}</code>
          <button
            onClick={() => onSelect(null)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Back
          </button>
        </div>
        <pre className="flex-1 overflow-auto px-3 py-2 text-xs font-mono whitespace-pre-wrap">
          {files[selected]}
        </pre>
      </div>
    );
  }
  return (
    <ul className="py-1">
      {entries.map(([path, content]) => (
        <li key={path}>
          <button
            onClick={() => onSelect(path)}
            className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50 transition-colors flex items-center gap-2"
          >
            <FileText className="w-3 h-3 flex-shrink-0 text-muted-foreground/60" />
            <span className="font-mono truncate flex-1">{path}</span>
            <span className="text-muted-foreground/50 text-[10px] flex-shrink-0">
              {content.length}B
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
