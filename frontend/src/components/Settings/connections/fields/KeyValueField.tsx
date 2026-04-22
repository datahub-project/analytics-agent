import { Plus, X } from "lucide-react";

type Pair = { key: string; value: string };

export function KeyValueField({
  label,
  pairs,
  onChange,
  keyPlaceholder = "KEY",
  valuePlaceholder = "value",
  hint,
}: {
  label: string;
  pairs: Pair[];
  onChange: (p: Pair[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  hint?: string;
}) {
  const update = (i: number, field: "key" | "value", v: string) => {
    const next = pairs.map((p, j) => (j === i ? { ...p, [field]: v } : p));
    onChange(next);
  };
  const remove = (i: number) => onChange(pairs.filter((_, j) => j !== i));
  const add = () => onChange([...pairs, { key: "", value: "" }]);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">{label}</label>
        {hint && <span className="text-xs text-muted-foreground/50">{hint}</span>}
      </div>
      <div className="space-y-1">
        {pairs.map((p, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <input
              type="text"
              value={p.key}
              placeholder={keyPlaceholder}
              onChange={(e) => update(i, "key", e.target.value)}
              className="w-32 text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            <span className="text-muted-foreground/40 text-xs">=</span>
            <input
              type="text"
              value={p.value}
              placeholder={valuePlaceholder}
              onChange={(e) => update(i, "value", e.target.value)}
              className="flex-1 text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-muted-foreground/40 hover:text-red-500 transition-colors p-0.5"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={add}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
        >
          <Plus className="w-3 h-3" /> Add
        </button>
      </div>
    </div>
  );
}
