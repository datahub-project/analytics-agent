import { useEffect, useRef, useState } from "react";
import { Save, RotateCcw, Loader2 } from "lucide-react";
import {
  getLargeToolResults,
  saveLargeToolResults,
  type LargeToolResultsSettings,
} from "@/api/settings";

export function AdvancedSection() {
  const [data, setData] = useState<LargeToolResultsSettings | null>(null);
  const [value, setValue] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLargeToolResults()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setValue(String(d.token_limit));
        initialRef.current = d.token_limit;
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const parsed = Number.parseInt(value, 10);
  const isValid = Number.isFinite(parsed) && parsed >= 0;
  const dirty = data !== null && isValid && parsed !== initialRef.current;

  const handleSave = async () => {
    if (!isValid) return;
    setSaving(true);
    setError(null);
    try {
      await saveLargeToolResults(parsed);
      initialRef.current = parsed;
      setData((prev) => (prev ? { ...prev, token_limit: parsed } : prev));
      setSavedAt(Date.now());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!data) return;
    setValue(String(data.default_token_limit));
  };

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">Large tool-result eviction</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Tool results above this token count get written to{" "}
            <code className="px-1 py-0.5 rounded bg-muted text-foreground/80">
              /large_tool_results/&lt;id&gt;
            </code>{" "}
            and replaced inline with a head/tail preview. The agent can then read
            or grep the file to extract just the slice it needs, instead of
            keeping the full payload in its context window.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            <strong>0</strong> disables eviction entirely. Lower values evict
            more aggressively (saves context but may force more file reads);
            higher values keep more results inline.
          </p>
        </div>

        <div className="flex items-end gap-3">
          <div className="flex-1 max-w-xs">
            <label className="text-xs text-muted-foreground block mb-1">
              Token limit
            </label>
            <input
              type="number"
              min={0}
              step={1000}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <button
            onClick={handleSave}
            disabled={!isValid || !dirty || saving}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Save className="w-3.5 h-3.5" />
            )}
            Save
          </button>
          <button
            onClick={handleReset}
            disabled={!data || parsed === data.default_token_limit}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-md border border-border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title={`Reset to default (${data?.default_token_limit ?? "—"})`}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Default
          </button>
        </div>

        {data && (
          <p className="text-xs text-muted-foreground">
            Default from environment / config:{" "}
            <code className="px-1 py-0.5 rounded bg-muted">
              {data.default_token_limit.toLocaleString()}
            </code>
            {parsed === 0 && (
              <span className="ml-2 text-amber-600 dark:text-amber-400">
                Eviction is disabled — large tool results will stay inline.
              </span>
            )}
          </p>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}
        {savedAt && !error && (
          <p className="text-xs text-green-600 dark:text-green-400">Saved.</p>
        )}
      </section>
    </div>
  );
}
