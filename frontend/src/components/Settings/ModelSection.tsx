import { useState, useEffect } from "react";
import { Check, Eye, EyeOff, Loader2, X } from "lucide-react";
import { getLlmSettings, saveLlmSettings, testLlmKey } from "@/api/settings";

type Provider = "anthropic" | "openai" | "google";

const MODELS: Record<Provider, { value: string; label: string; note: string }[]> = {
  anthropic: [
    { value: "claude-opus-4-7",           label: "Claude Opus 4.7",    note: "Most capable" },
    { value: "claude-sonnet-4-6",         label: "Claude Sonnet 4.6",  note: "Recommended"  },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5",   note: "Fastest"      },
  ],
  openai: [
    { value: "gpt-4o",      label: "GPT-4o",      note: "Recommended" },
    { value: "gpt-4o-mini", label: "GPT-4o Mini", note: "Fastest"     },
    { value: "o1",          label: "o1",           note: "Reasoning"   },
  ],
  google: [
    { value: "gemini-2.0-flash", label: "Gemini 2.0 Flash", note: "Recommended" },
    { value: "gemini-1.5-pro",   label: "Gemini 1.5 Pro",   note: "Most capable" },
    { value: "gemini-1.5-flash", label: "Gemini 1.5 Flash", note: "Fastest"      },
  ],
};

type KeyStatus =
  | { state: "idle" }
  | { state: "testing" }
  | { state: "ok"; msg: string }
  | { state: "fail"; msg: string };

type SaveStatus = "idle" | "saving" | "saved" | "error";

export function ModelSection() {
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState(MODELS.anthropic[1].value);
  const [apiKey, setApiKey] = useState("");
  // Track which provider the saved key belongs to so switching away and back
  // correctly shows/hides the "Key saved" placeholder.
  const [savedProvider, setSavedProvider] = useState<Provider | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [keyStatus, setKeyStatus] = useState<KeyStatus>({ state: "idle" });
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const hasExistingKey = savedProvider === provider && !apiKey;

  useEffect(() => {
    getLlmSettings()
      .then((s) => {
        const p = (s.provider ?? "anthropic") as Provider;
        const knownProvider = p in MODELS ? p : "anthropic";
        setProvider(knownProvider);
        const knownModels = MODELS[knownProvider].map((m) => m.value);
        setModel(knownModels.includes(s.model) ? s.model : MODELS[knownProvider][1].value);
        if (s.has_key) setSavedProvider(knownProvider);
      })
      .finally(() => setLoading(false));
  }, []);

  // Reset key status whenever provider or key changes
  useEffect(() => { setKeyStatus({ state: "idle" }); }, [apiKey, provider]);
  // Reset save status on any change
  useEffect(() => { setSaveStatus("idle"); setError(null); }, [provider, model, apiKey]);

  const handleProvider = (p: Provider) => {
    setProvider(p);
    setModel(MODELS[p][1].value);
    setApiKey("");
    // Don't clear savedProvider — switching back should restore the indicator
  };

  const runKeyTest = async (): Promise<boolean> => {
    if (!apiKey.trim()) return hasExistingKey; // no new key — existing one is fine
    setKeyStatus({ state: "testing" });
    try {
      const result = await testLlmKey({ provider, api_key: apiKey.trim(), model });
      setKeyStatus(result.ok
        ? { state: "ok", msg: result.message }
        : { state: "fail", msg: result.message }
      );
      return result.ok;
    } catch {
      setKeyStatus({ state: "fail", msg: "Can't reach the server to verify key" });
      return false;
    }
  };

  const handleSave = async () => {
    setError(null);
    setSaveStatus("saving");
    try {
      // Verify new key if one was entered
      if (apiKey.trim()) {
        if (keyStatus.state !== "ok") {
          const ok = await runKeyTest();
          if (!ok) { setSaveStatus("error"); return; }
        }
      } else if (!hasExistingKey) {
        setError("Enter an API key to save.");
        setSaveStatus("error");
        return;
      }
      await saveLlmSettings({ provider, api_key: apiKey.trim(), model });
      if (apiKey.trim()) {
        setSavedProvider(provider);
        setApiKey("");
        setKeyStatus({ state: "idle" });
      }
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2500);
    } catch (e) {
      setError(String(e).replace(/^(TypeError|Error):\s*/i, ""));
      setSaveStatus("error");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  const keyPlaceholder = hasExistingKey && !apiKey
    ? "Key saved — enter a new one to change"
    : provider === "anthropic" ? "sk-ant-api03-…"
    : provider === "google" ? "AIza…"
    : "sk-proj-…";

  return (
    <div className="max-w-lg space-y-8">
      {/* Provider */}
      <div className="space-y-3">
        <label className="text-sm font-medium text-foreground">Provider</label>
        <div className="flex rounded-xl border border-border p-1 gap-1 w-fit">
          {(["anthropic", "openai", "google"] as Provider[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => handleProvider(p)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150
                ${provider === p
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
                }`}
            >
              {p === "anthropic" ? "Anthropic" : p === "openai" ? "OpenAI" : "Google"}
            </button>
          ))}
        </div>
      </div>

      {/* Model */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-foreground">Model</label>
        <div className="space-y-1">
          {MODELS[provider].map((m) => {
            const active = model === m.value;
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => setModel(m.value)}
                className={`w-full flex items-center gap-4 px-4 py-3 rounded-xl text-left
                  transition-all duration-150 border
                  ${active
                    ? "border-primary/30 bg-primary/[0.05]"
                    : "border-transparent hover:border-border hover:bg-muted/40"
                  }`}
              >
                <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center
                  transition-all duration-150
                  ${active ? "border-primary bg-primary" : "border-border"}`}>
                  {active && <div className="w-2 h-2 rounded-full bg-white" />}
                </div>
                <div className="flex-1 min-w-0">
                  <span className={`text-sm font-medium ${active ? "text-foreground" : "text-foreground/80"}`}>
                    {m.label}
                  </span>
                </div>
                <span className={`text-xs flex-shrink-0
                  ${active ? "text-primary/70" : "text-muted-foreground/50"}`}>
                  {m.note}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* API key */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-foreground">API key</label>
        <div className="relative">
          <input
            type={showKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onBlur={() => { if (apiKey.trim()) runKeyTest(); }}
            placeholder={keyPlaceholder}
            className={`w-full bg-background border rounded-xl px-4 py-3 text-sm font-mono
              focus:outline-none focus:ring-2 focus:ring-primary/25
              placeholder:text-muted-foreground/30 transition-all pr-11
              ${keyStatus.state === "ok"   ? "border-emerald-500/50 focus:border-emerald-500/60"
              : keyStatus.state === "fail" ? "border-red-400/50 focus:border-red-400/60"
              : "border-border focus:border-primary/50"}`}
          />
          <button
            type="button"
            onClick={() => setShowKey((v) => !v)}
            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground/40
                       hover:text-muted-foreground transition-colors"
          >
            {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>

        {/* Key status line */}
        {keyStatus.state === "testing" && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" /> Verifying key…
          </p>
        )}
        {keyStatus.state === "ok" && (
          <p className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
            <Check className="w-3 h-3" strokeWidth={3} /> {keyStatus.msg}
          </p>
        )}
        {keyStatus.state === "fail" && (
          <p className="flex items-center gap-1.5 text-xs text-red-500">
            <X className="w-3 h-3" strokeWidth={3} /> {keyStatus.msg}
          </p>
        )}
        {keyStatus.state === "idle" && !hasExistingKey && (
          <p className="text-xs text-muted-foreground/50">
            {provider === "anthropic"
              ? "console.anthropic.com/settings/api-keys"
              : provider === "google"
              ? "aistudio.google.com/app/apikey"
              : "platform.openai.com/api-keys"}
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <p className="text-sm text-red-500 bg-red-500/8 border border-red-500/20 rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* Save button */}
      <button
        type="button"
        onClick={handleSave}
        disabled={saveStatus === "saving"}
        className="flex items-center gap-2 text-sm px-6 py-2.5 rounded-xl font-medium
                   bg-primary text-primary-foreground hover:bg-primary/90
                   transition-colors disabled:opacity-40"
      >
        {saveStatus === "saving" && <Loader2 className="w-4 h-4 animate-spin" />}
        {saveStatus === "saved"  && <Check  className="w-4 h-4" strokeWidth={3} />}
        {saveStatus === "saved" ? "Saved!" : "Save"}
      </button>
    </div>
  );
}
