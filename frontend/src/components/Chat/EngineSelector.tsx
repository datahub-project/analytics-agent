import type { Engine } from "@/types";
import { Database } from "lucide-react";

interface Props {
  engines: Engine[];
  selected: string;
  onChange: (name: string) => void;
  disabled?: boolean;
}

export function EngineSelector({ engines, selected, onChange, disabled }: Props) {
  if (engines.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5">
      <Database className="w-3.5 h-3.5 text-muted-foreground" />
      <select
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="text-xs bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
      >
        {engines.map((e) => (
          <option key={e.name} value={e.name}>
            {e.name}
          </option>
        ))}
      </select>
    </div>
  );
}
