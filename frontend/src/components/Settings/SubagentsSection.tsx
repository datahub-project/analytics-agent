import { useEffect, useMemo, useState } from "react";
import { Check, Loader2, Plus, RotateCcw, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import {
  getSubagentsConfig,
  saveSubagentsConfig,
  type BuiltinSubagent,
  type CustomSubagent,
  type BuiltinOverride,
} from "@/api/settings";

type SaveStatus = "idle" | "saving" | "saved" | "error";

interface BuiltinRowState {
  spec: BuiltinSubagent;
  enabled: boolean;
  expanded: boolean;
  override: BuiltinOverride;
}

function emptyCustom(): CustomSubagent {
  return { name: "", description: "", system_prompt: "", tool_names: [] };
}

export function SubagentsSection() {
  const [builtins, setBuiltins] = useState<BuiltinRowState[]>([]);
  const [custom, setCustom] = useState<CustomSubagent[]>([]);
  const [availableTools, setAvailableTools] = useState<string[]>([]);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSubagentsConfig()
      .then((cfg) => {
        if (cancelled) return;
        const disabled = new Set(cfg.disabled_builtins);
        setBuiltins(
          cfg.builtins.map((spec) => ({
            spec,
            enabled: !disabled.has(spec.name),
            expanded: false,
            override: cfg.builtin_overrides[spec.name] ?? {},
          })),
        );
        setCustom(cfg.custom);
        setAvailableTools(cfg.available_tools);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setSaveStatus("saving");
    setError(null);
    try {
      const disabled_builtins = builtins.filter((b) => !b.enabled).map((b) => b.spec.name);
      const builtin_overrides: Record<string, BuiltinOverride> = {};
      for (const b of builtins) {
        // Only persist overrides that diverge from the spec default. A
        // tool_names list that's null/empty means "use the builtin selector".
        const rec: BuiltinOverride = {};
        if (b.override.description && b.override.description !== b.spec.description) {
          rec.description = b.override.description;
        }
        if (b.override.system_prompt && b.override.system_prompt !== b.spec.system_prompt) {
          rec.system_prompt = b.override.system_prompt;
        }
        if (b.override.tool_names && b.override.tool_names.length > 0) {
          rec.tool_names = b.override.tool_names;
        }
        if (Object.keys(rec).length > 0) {
          builtin_overrides[b.spec.name] = rec;
        }
      }
      // Filter out incomplete custom rows.
      const safeCustom = custom.filter(
        (c) => c.name.trim() && c.description.trim() && c.system_prompt.trim() && c.tool_names.length,
      );
      await saveSubagentsConfig({ disabled_builtins, builtin_overrides, custom: safeCustom });
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (e) {
      setSaveStatus("error");
      setError(String(e));
    }
  };

  return (
    <div className="space-y-6">
      <div className="text-xs text-muted-foreground leading-relaxed">
        Builtin sub-agents are shipped defaults. Toggle them off to remove from
        the agent's toolkit, or expand to override the description, system
        prompt, or tool list. Add custom sub-agents below — each runs in an
        isolated context window and only its summary returns to the parent.
      </div>

      <section className="space-y-3">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Built-in sub-agents
        </div>
        <div className="rounded-xl border border-border divide-y divide-border">
          {builtins.map((b, idx) => (
            <BuiltinRow
              key={b.spec.name}
              row={b}
              availableTools={availableTools}
              onChange={(next) =>
                setBuiltins((prev) => prev.map((p, i) => (i === idx ? next : p)))
              }
            />
          ))}
          {builtins.length === 0 && (
            <div className="px-4 py-6 text-sm text-muted-foreground">Loading…</div>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Custom sub-agents
          </div>
          <button
            type="button"
            onClick={() => setCustom((prev) => [...prev, emptyCustom()])}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border hover:bg-muted/50 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Add sub-agent
          </button>
        </div>
        {custom.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-muted-foreground text-center">
            No custom sub-agents yet.
          </div>
        ) : (
          <div className="space-y-3">
            {custom.map((c, idx) => (
              <CustomRow
                key={idx}
                rec={c}
                availableTools={availableTools}
                onChange={(next) =>
                  setCustom((prev) => prev.map((p, i) => (i === idx ? next : p)))
                }
                onDelete={() => setCustom((prev) => prev.filter((_, i) => i !== idx))}
              />
            ))}
          </div>
        )}
      </section>

      {error && (
        <p className="text-sm text-red-500 bg-red-500/8 border border-red-500/20 rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={handleSave}
        disabled={saveStatus === "saving"}
        className="flex items-center gap-2 text-sm px-6 py-2.5 rounded-xl font-medium
                   bg-primary text-primary-foreground hover:bg-primary/90
                   transition-colors disabled:opacity-40"
      >
        {saveStatus === "saving" && <Loader2 className="w-4 h-4 animate-spin" />}
        {saveStatus === "saved" && <Check className="w-4 h-4" strokeWidth={3} />}
        {saveStatus === "saved" ? "Saved!" : "Save"}
      </button>
    </div>
  );
}

function BuiltinRow({
  row,
  availableTools,
  onChange,
}: {
  row: BuiltinRowState;
  availableTools: string[];
  onChange: (next: BuiltinRowState) => void;
}) {
  const { spec, enabled, expanded, override } = row;
  const description = override.description ?? spec.description;
  const systemPrompt = override.system_prompt ?? spec.system_prompt;
  const toolNamesOverride = override.tool_names ?? null;

  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => onChange({ ...row, expanded: !expanded })}
          className="mt-0.5 text-muted-foreground hover:text-foreground"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
        <input
          type="checkbox"
          className="mt-1"
          checked={enabled}
          onChange={() => onChange({ ...row, enabled: !enabled })}
        />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium flex items-center gap-2">
            {spec.name}
            {spec.has_response_format && (
              <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                typed result
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {description}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="mt-4 ml-7 space-y-4">
          <Field label="Description">
            <textarea
              className="w-full text-sm rounded-lg border border-border bg-background px-3 py-2 min-h-[60px]"
              value={description}
              onChange={(e) => onChange({ ...row, override: { ...override, description: e.target.value } })}
            />
          </Field>
          <Field label="System prompt">
            <textarea
              className="w-full text-sm font-mono rounded-lg border border-border bg-background px-3 py-2 min-h-[140px]"
              value={systemPrompt}
              onChange={(e) => onChange({ ...row, override: { ...override, system_prompt: e.target.value } })}
            />
          </Field>
          <Field
            label="Tools"
            help={
              toolNamesOverride
                ? "Custom tool list — the builtin selector is overridden."
                : "Auto: this builtin picks its tools from the available pool. Override with an explicit list below."
            }
          >
            <ToolPicker
              available={availableTools}
              selected={toolNamesOverride ?? []}
              onChange={(names) =>
                onChange({
                  ...row,
                  override: { ...override, tool_names: names.length > 0 ? names : null },
                })
              }
            />
            {toolNamesOverride && (
              <button
                type="button"
                onClick={() => onChange({ ...row, override: { ...override, tool_names: null } })}
                className="flex items-center gap-1.5 text-xs mt-2 text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="w-3 h-3" /> Reset to auto
              </button>
            )}
          </Field>
        </div>
      )}
    </div>
  );
}

function CustomRow({
  rec,
  availableTools,
  onChange,
  onDelete,
}: {
  rec: CustomSubagent;
  availableTools: string[];
  onChange: (next: CustomSubagent) => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-xl border border-border p-4 space-y-3">
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-3">
          <Field label="Name">
            <input
              type="text"
              className="w-full text-sm font-mono rounded-lg border border-border bg-background px-3 py-2"
              placeholder="kebab-case-name"
              value={rec.name}
              onChange={(e) => onChange({ ...rec, name: e.target.value.replace(/\s+/g, "-").toLowerCase() })}
            />
          </Field>
          <Field label="Description" help="When the parent agent should delegate to this sub-agent.">
            <textarea
              className="w-full text-sm rounded-lg border border-border bg-background px-3 py-2 min-h-[60px]"
              value={rec.description}
              onChange={(e) => onChange({ ...rec, description: e.target.value })}
            />
          </Field>
          <Field label="System prompt" help="Instructions the sub-agent runs under.">
            <textarea
              className="w-full text-sm font-mono rounded-lg border border-border bg-background px-3 py-2 min-h-[140px]"
              value={rec.system_prompt}
              onChange={(e) => onChange({ ...rec, system_prompt: e.target.value })}
            />
          </Field>
          <Field label="Tools">
            <ToolPicker
              available={availableTools}
              selected={rec.tool_names}
              onChange={(names) => onChange({ ...rec, tool_names: names })}
            />
          </Field>
        </div>
        <button
          type="button"
          onClick={onDelete}
          className="text-muted-foreground hover:text-red-500 transition-colors"
          aria-label="Delete sub-agent"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground mb-1.5">{label}</div>
      {children}
      {help && <div className="text-xs text-muted-foreground mt-1">{help}</div>}
    </div>
  );
}

function ToolPicker({
  available,
  selected,
  onChange,
}: {
  available: string[];
  selected: string[];
  onChange: (names: string[]) => void;
}) {
  const [filter, setFilter] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const filtered = available.filter((t) => t.toLowerCase().includes(filter.toLowerCase()));

  const toggle = (t: string) => {
    if (selectedSet.has(t)) onChange(selected.filter((s) => s !== t));
    else onChange([...selected, t]);
  };

  return (
    <div className="space-y-2">
      <input
        type="text"
        placeholder="Filter tools…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full text-xs rounded-lg border border-border bg-background px-3 py-1.5"
      />
      <div className="max-h-44 overflow-y-auto rounded-lg border border-border bg-background/50 p-2 space-y-1">
        {filtered.map((t) => (
          <label key={t} className="flex items-center gap-2 text-xs px-2 py-1 hover:bg-muted/50 rounded cursor-pointer">
            <input type="checkbox" checked={selectedSet.has(t)} onChange={() => toggle(t)} />
            <code className="font-mono">{t}</code>
          </label>
        ))}
        {filtered.length === 0 && <div className="text-xs text-muted-foreground px-2 py-1">No matches.</div>}
      </div>
      <div className="text-xs text-muted-foreground">
        {selected.length} selected.
      </div>
    </div>
  );
}
