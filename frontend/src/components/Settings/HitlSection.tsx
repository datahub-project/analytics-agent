import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { getHitlPolicy, saveHitlPolicy } from "@/api/settings";

type SaveStatus = "idle" | "saving" | "saved" | "error";

// Hand-curated metadata for the catalog-mutation-class tools so the UI can
// describe each row. Anything in `available_tools` that's not in the map
// renders with a sensible fallback.
const TOOL_INFO: Record<string, { label: string; description: string; group: string }> = {
  add_tags:                         { label: "Add tags",                      description: "Attach tags to a DataHub entity",                            group: "DataHub" },
  remove_tags:                      { label: "Remove tags",                   description: "Strip tags from a DataHub entity",                           group: "DataHub" },
  add_terms:                        { label: "Add glossary terms",            description: "Attach business glossary terms to an entity",                group: "DataHub" },
  remove_terms:                     { label: "Remove glossary terms",         description: "Strip glossary terms from an entity",                        group: "DataHub" },
  update_description:               { label: "Update description",            description: "Edit an entity's description",                               group: "DataHub" },
  update_glossary_term_description: { label: "Update glossary term docs",     description: "Edit a glossary term's authoritative definition",            group: "DataHub" },
  set_domains:                      { label: "Set domains",                   description: "Assign an entity to a domain",                               group: "DataHub" },
  set_owners:                       { label: "Set owners",                    description: "Set ownership on an entity",                                 group: "DataHub" },
  remove_owners:                    { label: "Remove owners",                 description: "Clear ownership on an entity",                               group: "DataHub" },
  save_document:                    { label: "Save document",                 description: "Create or update a DataHub document (analyses, runbooks, …)", group: "DataHub" },
  delete_entity:                    { label: "Delete entity",                 description: "Soft-delete a DataHub entity",                               group: "DataHub" },
  publish_analysis:                 { label: "Publish analysis",              description: "Save a completed analysis as a DataHub document",            group: "Skills" },
  save_correction:                  { label: "Save correction",               description: "Fix a glossary term / dataset description in DataHub",       group: "Skills" },
  execute:                          { label: "Shell execute",                 description: "Run an arbitrary shell command in the per-conversation sandbox", group: "Sandbox" },
};

export function HitlSection() {
  const [available, setAvailable] = useState<string[]>([]);
  // What's actually being gated right now — used as the rendered
  // checkbox state, regardless of defaults vs custom mode.
  const [intercepted, setIntercepted] = useState<Set<string>>(new Set());
  const [usingDefaults, setUsingDefaults] = useState(true);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHitlPolicy()
      .then((p) => {
        if (cancelled) return;
        setAvailable(p.available_tools);
        // Render the EFFECTIVE list — in defaults mode that's the
        // computed defaults; in custom mode it's the override. Either
        // way the user sees what's currently active and can edit it.
        setIntercepted(new Set(p.effective_tools));
        setUsingDefaults(p.interrupt_tools.length === 0);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (tool: string) => {
    setIntercepted((prev) => {
      const next = new Set(prev);
      if (next.has(tool)) next.delete(tool);
      else next.add(tool);
      return next;
    });
    // First check/uncheck flips the user out of defaults mode. The
    // checkbox state already shows the effective set, so the change
    // is purely additive/subtractive from the user's POV.
    setUsingDefaults(false);
    setSaveStatus("idle");
  };

  const setDefaults = async () => {
    // Reset clears the override AND re-fetches so the rendered
    // checkbox state matches the freshly-computed defaults.
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
      // In defaults mode we still send [] so the backend keeps using
      // the computed list. Otherwise persist the explicit set.
      await saveHitlPolicy(usingDefaults ? [] : Array.from(intercepted));
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (e) {
      setSaveStatus("error");
      setError(String(e));
    }
  };

  // Group tools for display; fall back to "Other" for anything in
  // available_tools we don't recognize.
  const grouped = available.reduce<Record<string, string[]>>((acc, t) => {
    const grp = TOOL_INFO[t]?.group ?? "Other";
    (acc[grp] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-amber-500/30 bg-amber-50/30 dark:bg-amber-950/20 p-4">
        <div className="flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-muted-foreground leading-relaxed">
            When the agent calls one of the checked tools, it pauses and waits
            for you to <strong>approve, reject, or edit</strong> the call before
            it runs. Read-only tools (search, get_entities, execute_sql, …) are
            never gated. Per-conversation "trust this session" remains
            available in the chat.
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
          {Object.entries(grouped).map(([group, tools]) => (
            <div key={group} className="space-y-2">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                {group}
              </div>
              <div className="rounded-xl border border-border divide-y divide-border">
                {tools.map((tool) => {
                  const info = TOOL_INFO[tool];
                  const checked = intercepted.has(tool);
                  return (
                    <label
                      key={tool}
                      className="flex items-start gap-3 px-4 py-3 hover:bg-muted/30 cursor-pointer transition-colors"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={checked}
                        onChange={() => toggle(tool)}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium">
                          {info?.label ?? tool}{" "}
                          <code className="ml-1 px-1.5 py-0.5 bg-muted text-muted-foreground rounded text-xs font-mono">
                            {tool}
                          </code>
                        </div>
                        {info?.description && (
                          <div className="text-xs text-muted-foreground mt-0.5">
                            {info.description}
                          </div>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
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
