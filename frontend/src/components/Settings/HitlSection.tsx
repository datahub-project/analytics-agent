import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { getHitlPolicy, saveHitlPolicy, type HitlToolInfo } from "@/api/settings";

type SaveStatus = "idle" | "saving" | "saved" | "error";

// Hand-curated descriptions for the canonical mutation tools. Anything
// not in the map renders with just its tool name.
const TOOL_DESCRIPTIONS: Record<string, string> = {
  add_tags: "Attach tags to a DataHub entity",
  remove_tags: "Strip tags from a DataHub entity",
  add_terms: "Attach business glossary terms to an entity",
  remove_terms: "Strip glossary terms from an entity",
  update_description: "Edit an entity's description",
  update_glossary_term_description: "Edit a glossary term's authoritative definition",
  set_domains: "Assign an entity to a domain",
  set_owners: "Set ownership on an entity",
  remove_owners: "Clear ownership on an entity",
  save_document: "Create or update a DataHub document",
  delete_entity: "Soft-delete a DataHub entity",
  publish_analysis: "Save a completed analysis as a DataHub document",
  save_correction: "Fix a glossary term / dataset description in DataHub",
  execute: "Run an arbitrary shell command in the per-conversation sandbox",
};

interface SourceGroup {
  source: string;
  mutations: HitlToolInfo[];
  readonly: HitlToolInfo[];
}

export function HitlSection() {
  const [available, setAvailable] = useState<HitlToolInfo[]>([]);
  const [intercepted, setIntercepted] = useState<Set<string>>(new Set());
  const [usingDefaults, setUsingDefaults] = useState(true);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  // Per-source expand/collapse for the read-only subgroup.
  const [readonlyExpanded, setReadonlyExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    getHitlPolicy()
      .then((p) => {
        if (cancelled) return;
        setAvailable(p.available_tools);
        setIntercepted(new Set(p.effective_tools));
        setUsingDefaults(p.interrupt_tools.length === 0);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped: SourceGroup[] = useMemo(() => {
    const bySource = new Map<string, SourceGroup>();
    for (const t of available) {
      const grp = bySource.get(t.source) ?? { source: t.source, mutations: [], readonly: [] };
      (t.is_mutation ? grp.mutations : grp.readonly).push(t);
      bySource.set(t.source, grp);
    }
    // Stable ordering: groups with any mutations first; within each, tools alphabetical.
    const groups = Array.from(bySource.values()).sort((a, b) => {
      const aHas = a.mutations.length > 0 ? 0 : 1;
      const bHas = b.mutations.length > 0 ? 0 : 1;
      if (aHas !== bHas) return aHas - bHas;
      return a.source.localeCompare(b.source);
    });
    for (const g of groups) {
      g.mutations.sort((a, b) => a.name.localeCompare(b.name));
      g.readonly.sort((a, b) => a.name.localeCompare(b.name));
    }
    return groups;
  }, [available]);

  const toggle = (tool: string) => {
    setIntercepted((prev) => {
      const next = new Set(prev);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return next;
    });
    setUsingDefaults(false);
    setSaveStatus("idle");
  };

  const setDefaults = async () => {
    setSaveStatus("saving");
    setError(null);
    try {
      await saveHitlPolicy([]);
      const fresh = await getHitlPolicy();
      setIntercepted(new Set(fresh.effective_tools));
      setUsingDefaults(true);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (e) {
      setSaveStatus("error");
      setError(String(e));
    }
  };

  const handleSave = async () => {
    setSaveStatus("saving");
    setError(null);
    try {
      await saveHitlPolicy(usingDefaults ? [] : Array.from(intercepted));
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (e) {
      setSaveStatus("error");
      setError(String(e));
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-amber-500/30 bg-amber-50/30 dark:bg-amber-950/20 p-4">
        <div className="flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-muted-foreground leading-relaxed">
            When the agent calls one of the checked tools, it pauses and waits
            for you to <strong>approve, reject, or edit</strong> the call before
            it runs. Each group below shows tools by source — known mutation
            tools are shown by default; read-only or unclassified tools (mostly
            harmless to skip) are collapsed.
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">Mode</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {usingDefaults
                ? "Using built-in defaults: DataHub catalog mutations + your enabled write-back skills."
                : "Custom override: only the tools you check below will pause for approval."}
            </div>
          </div>
          {!usingDefaults && (
            <button
              type="button"
              onClick={setDefaults}
              className="text-xs px-3 py-1.5 rounded-lg border border-border hover:bg-muted/50 transition-colors"
            >
              Reset to defaults
            </button>
          )}
        </div>

        <div className="space-y-4">
          {grouped.map((g) => {
            const roOpen = readonlyExpanded[g.source] ?? false;
            return (
              <div key={g.source} className="space-y-2">
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  {g.source}
                </div>
                <div className="rounded-xl border border-border divide-y divide-border">
                  {g.mutations.map((t) => (
                    <ToolRow key={t.name} tool={t} checked={intercepted.has(t.name)} onToggle={toggle} />
                  ))}
                  {g.readonly.length > 0 && (
                    <div>
                      <button
                        type="button"
                        onClick={() =>
                          setReadonlyExpanded((prev) => ({ ...prev, [g.source]: !roOpen }))
                        }
                        className="w-full flex items-center justify-between gap-2 px-4 py-2.5 text-xs text-muted-foreground hover:bg-muted/30 transition-colors"
                      >
                        <span className="flex items-center gap-1.5">
                          {roOpen ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                          Read-only / unclassified
                        </span>
                        <span>{g.readonly.length} tool{g.readonly.length === 1 ? "" : "s"}</span>
                      </button>
                      {roOpen && (
                        <div className="divide-y divide-border">
                          {g.readonly.map((t) => (
                            <ToolRow
                              key={t.name}
                              tool={t}
                              checked={intercepted.has(t.name)}
                              onToggle={toggle}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {g.mutations.length === 0 && g.readonly.length === 0 && (
                    <div className="px-4 py-3 text-xs text-muted-foreground">No tools.</div>
                  )}
                </div>
              </div>
            );
          })}
          {grouped.length === 0 && (
            <div className="text-xs text-muted-foreground">Loading…</div>
          )}
        </div>
      </div>

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

function ToolRow({
  tool,
  checked,
  onToggle,
}: {
  tool: HitlToolInfo;
  checked: boolean;
  onToggle: (name: string) => void;
}) {
  const description = TOOL_DESCRIPTIONS[tool.name];
  return (
    <label className="flex items-start gap-3 px-4 py-3 hover:bg-muted/30 cursor-pointer transition-colors">
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={() => onToggle(tool.name)} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium flex items-center gap-2 flex-wrap">
          <code className="px-1.5 py-0.5 bg-muted text-muted-foreground rounded text-xs font-mono">
            {tool.name}
          </code>
          {tool.is_mutation && (
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300">
              mutation
            </span>
          )}
        </div>
        {description && (
          <div className="text-xs text-muted-foreground mt-0.5">{description}</div>
        )}
      </div>
    </label>
  );
}
