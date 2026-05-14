import { useState, useEffect } from "react";
import { Check, Eye, EyeOff, Loader2, X } from "lucide-react";
import { getLlmSettings, saveLlmSettings, testLlmKey } from "@/api/settings";

type Provider = "anthropic" | "openai" | "google" | "bedrock" | "openai-compatible";
type HeaderPair = { key: string; value: string };

// Sentinel value for the "Custom…" radio option on providers (Bedrock) where
// users commonly need to pin a specific model ID / inference profile.
const CUSTOM_MODEL_VALUE = "__custom__";

const MODELS = {
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
  bedrock: [
    { value: "us.anthropic.claude-sonnet-4-5-20250929-v1:0", label: "Claude Sonnet 4.5 (Bedrock)", note: "Recommended" },
    { value: "us.anthropic.claude-haiku-4-5-20251001-v1:0",  label: "Claude Haiku 4.5 (Bedrock)",  note: "Fastest"     },
    { value: CUSTOM_MODEL_VALUE,                              label: "Custom model ID",            note: "Enter your own" },
  ],
} as Record<Exclude<Provider, "openai-compatible">, { value: string; label: string; note: string }[]>;

function defaultModelFor(p: Provider): string {
  if (p === "openai-compatible") return "";
  return p === "bedrock" ? MODELS[p][0].value : MODELS[p][1].value;
}

type KeyStatus =
  | { state: "idle" }
  | { state: "testing" }
  | { state: "ok"; msg: string }
  | { state: "fail"; msg: string };

type SaveStatus = "idle" | "saving" | "saved" | "error";

export function ModelSection() {
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState(defaultModelFor("anthropic"));
  const [customModel, setCustomModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  // Bedrock-only credential fields.
  const [awsRegion, setAwsRegion] = useState("us-west-2");
  const [awsAccessKey, setAwsAccessKey] = useState("");
  const [awsSecret, setAwsSecret] = useState("");
  const [awsSessionToken, setAwsSessionToken] = useState("");
  const [showSessionToken, setShowSessionToken] = useState(false);
  const [enablePromptCache, setEnablePromptCache] = useState(true);
  // OpenAI-compatible provider fields.
  const [customUrl, setCustomUrl] = useState("");
  const [customHeaders, setCustomHeaders] = useState<HeaderPair[]>([]);
  const [showModelInput, setShowModelInput] = useState(false);
  // Track which provider the saved key belongs to so switching away and back
  // correctly shows/hides the "Key saved" placeholder.
  const [savedProvider, setSavedProvider] = useState<Provider | null>(null);
  const [hasSavedAwsKeys, setHasSavedAwsKeys] = useState(false);
  const [savedHeaderKeys, setSavedHeaderKeys] = useState<string[]>([]);
  const [showKey, setShowKey] = useState(false);
  const [showAwsSecret, setShowAwsSecret] = useState(false);
  const [keyStatus, setKeyStatus] = useState<KeyStatus>({ state: "idle" });
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const isCustomModel = model === CUSTOM_MODEL_VALUE;
  const effectiveModel =
    provider === "openai-compatible" ? customModel.trim() : isCustomModel ? customModel.trim() : model;
  const hasExistingKey = savedProvider === provider && !apiKey;
  // Bedrock has a separate "configured" concept — either stored keys OR the
  // user opted into the system credential chain by saving with blank fields.
  const hasExistingAwsKeys = provider === "bedrock" && hasSavedAwsKeys && !awsAccessKey && !awsSecret;

  useEffect(() => {
    getLlmSettings()
      .then((s) => {
        const p = (s.provider ?? "anthropic") as Provider;
        const knownProvider = (p in MODELS ? p : "anthropic") as Exclude<Provider, "openai-compatible">;
        setProvider(p);
        if (p === "openai-compatible") {
          // OpenAI-compatible provider: load URL, model, and headers from settings.
          // Fall back to s.model for users who saved via the original openai-compatible
          // form (which stored the model in the generic `model` DB key, not openai_compatible_model).
          setCustomUrl(s.base_url ?? "");
          const savedModel = s.openai_compatible_model || s.model || "";
          setCustomModel(savedModel);
          if (savedModel) setShowModelInput(true);
          if (s.has_openai_compatible_headers) {
            setSavedProvider(p);
            const keys = s.openai_compatible_header_keys ?? [];
            setSavedHeaderKeys(keys);
            // Pre-populate headers with keys but no values so user can update
            setCustomHeaders(keys.map(k => ({ key: k, value: "" })));
          }
        } else {
          const knownModels = MODELS[knownProvider].map((m) => m.value);
          if (s.model && knownModels.includes(s.model)) {
            setModel(s.model);
          } else if (s.model) {
            // Saved model isn't in the curated list — treat as custom.
            setModel(CUSTOM_MODEL_VALUE);
            setCustomModel(s.model);
          } else {
            setModel(defaultModelFor(knownProvider));
          }
          if (s.has_key) setSavedProvider(knownProvider);
        }
        if (s.aws_region) setAwsRegion(s.aws_region);
        if (s.has_aws_keys) setHasSavedAwsKeys(true);
        if (s.enable_prompt_cache !== undefined) setEnablePromptCache(s.enable_prompt_cache);
      })
      .finally(() => setLoading(false));
  }, []);

  // Reset key status whenever any credential field changes.
  useEffect(() => { setKeyStatus({ state: "idle" }); }, [apiKey, provider, awsAccessKey, awsSecret, awsRegion, awsSessionToken, customUrl, customHeaders]);
  // Reset save status on any change.
  useEffect(() => { setSaveStatus("idle"); setError(null); }, [provider, model, customModel, apiKey, awsAccessKey, awsSecret, awsRegion, awsSessionToken, enablePromptCache, customUrl, customHeaders]);

  const handleProvider = (p: Provider) => {
    setProvider(p);
    setModel(defaultModelFor(p));
    setCustomModel("");
    setCustomUrl("");
    setCustomHeaders([]);
    setShowModelInput(false);
    setApiKey("");
    setAwsAccessKey("");
    setAwsSecret("");
    setAwsSessionToken("");
    // Don't clear savedProvider / hasSavedAwsKeys — switching back should restore the indicator.
  };

  const buildTestPayload = () => ({
    provider,
    api_key: apiKey.trim(),
    model: effectiveModel,
    aws_region: awsRegion.trim(),
    aws_access_key_id: awsAccessKey.trim(),
    aws_secret_access_key: awsSecret.trim(),
    aws_session_token: awsSessionToken.trim(),
    base_url: customUrl.trim(),
    openai_compatible_model: customModel.trim(),
    openai_compatible_headers: customHeaders.length > 0 ? JSON.stringify(Object.fromEntries(customHeaders.map((h) => [h.key.trim(), h.value.trim()]))) : "",
  });

  const runKeyTest = async (): Promise<boolean> => {
    // For non-Bedrock/openai-compatible: nothing new to test if field is empty; existing key is fine.
    if (provider !== "bedrock" && provider !== "openai-compatible" && !apiKey.trim()) return hasExistingKey;
    // For Bedrock and custom: always testable — use either the typed creds or existing stored creds.
    setKeyStatus({ state: "testing" });
    try {
      const result = await testLlmKey(buildTestPayload());
      setKeyStatus(result.ok
        ? { state: "ok", msg: result.message }
        : { state: "fail", msg: result.message }
      );
      return result.ok;
    } catch {
      setKeyStatus({ state: "fail", msg: "Can't reach the server to verify" });
      return false;
    }
  };

  const handleSave = async () => {
    setError(null);
    if (isCustomModel && !customModel.trim()) {
      setError("Enter a model ID or pick one from the list.");
      setSaveStatus("error");
      return;
    }
    if (provider === "openai-compatible") {
      if (!customUrl.trim()) {
        setError("Enter the LLM backend URL.");
        setSaveStatus("error");
        return;
      }
    }
    setSaveStatus("saving");
    try {
      if (provider === "bedrock") {
        // Bedrock: no mandatory field — any save implies "use the default AWS
        // chain if keys are blank". Still run a test if the user hasn't yet.
        if (keyStatus.state !== "ok") {
          const ok = await runKeyTest();
          if (!ok) { setSaveStatus("error"); return; }
        }
      } else if (provider === "openai-compatible") {
        // OpenAI-compatible: always require a test before saving
        if (keyStatus.state !== "ok") {
          const ok = await runKeyTest();
          if (!ok) { setSaveStatus("error"); return; }
        }
      } else if (apiKey.trim()) {
        if (keyStatus.state !== "ok") {
          const ok = await runKeyTest();
          if (!ok) { setSaveStatus("error"); return; }
        }
      } else if (!hasExistingKey) {
        setError("Enter an API key to save.");
        setSaveStatus("error");
        return;
      }

      await saveLlmSettings({
        provider,
        api_key: apiKey.trim(),
        model: effectiveModel,
        aws_region: awsRegion.trim(),
        aws_access_key_id: awsAccessKey.trim(),
        aws_secret_access_key: awsSecret.trim(),
        aws_session_token: awsSessionToken.trim(),
        enable_prompt_cache: enablePromptCache,
        base_url: customUrl.trim(),
        openai_compatible_model: customModel.trim(),
        openai_compatible_headers: customHeaders.length > 0 ? JSON.stringify(Object.fromEntries(customHeaders.map((h) => [h.key.trim(), h.value.trim()]))) : "",
      });

      if (apiKey.trim()) {
        setSavedProvider(provider);
        setApiKey("");
      }
      if (customUrl.trim() && customModel.trim()) {
        setSavedProvider(provider);
      }
      if (awsAccessKey.trim() && awsSecret.trim()) {
        setHasSavedAwsKeys(true);
        setAwsAccessKey("");
        setAwsSecret("");
        setAwsSessionToken("");
      }
      setKeyStatus({ state: "idle" });
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

  const providerLabel = (p: Provider) =>
    p === "anthropic" ? "Anthropic"
    : p === "openai" ? "OpenAI"
    : p === "google" ? "Google"
    : p === "bedrock" ? "AWS Bedrock"
    : "OpenAI-compatible";

  return (
    <div className="max-w-lg space-y-8">
      {/* Provider */}
      <div className="space-y-3">
        <label className="text-sm font-medium text-foreground">Provider</label>
        <div className="flex flex-nowrap rounded-xl border border-border p-1 gap-1 w-fit max-w-full overflow-x-auto">
          {(["anthropic", "openai", "google", "bedrock", "openai-compatible"] as Provider[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => handleProvider(p)}
              className={`px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 whitespace-nowrap
                ${provider === p
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
                }`}
            >
              {providerLabel(p)}
            </button>
          ))}
        </div>
      </div>

      {/* Model — for known providers */}
      {provider !== "openai-compatible" && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">Model</label>
          <div className="space-y-1">
            {MODELS[provider as Exclude<Provider, "openai-compatible">].map((m) => {
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
          {isCustomModel && (
            <input
              type="text"
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder={provider === "bedrock"
                ? "us.anthropic.claude-opus-4-5-20251001-v1:0"
                : "model-id"}
              className="w-full mt-2 bg-background border border-border rounded-xl px-4 py-3
                         text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                         focus:border-primary/50 placeholder:text-muted-foreground/30"
            />
          )}
        </div>
      )}

      {/* Credentials — openai-compatible config, single key, or Bedrock AWS fields. */}
      {provider === "openai-compatible" ? (
        <div className="space-y-4 rounded-lg border border-border bg-muted/20 p-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground">
              LLM Backend URL <span className="text-primary">*</span>
            </label>
            <input
              type="text"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              placeholder="http://localhost:8000/v1"
              className="w-full mt-1 bg-background border border-border rounded-xl px-4 py-3
                         text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                         focus:border-primary/50 placeholder:text-muted-foreground/30"
            />
            <p className="text-xs text-muted-foreground/60 mt-1">OpenAI-compatible endpoint</p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Model Name</label>
            <p className="text-xs text-muted-foreground/60 mt-0.5 mb-2">Set by your proxy — override only if needed</p>
            {(showModelInput || customModel) ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="model-id"
                  className="flex-1 text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/30"
                />
                <button
                  type="button"
                  onClick={() => { setCustomModel(""); setShowModelInput(false); }}
                  className="text-muted-foreground/40 hover:text-red-500 transition-colors p-0.5"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowModelInput(true)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
              >
                + Set model name
              </button>
            )}
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Custom Headers (optional)</label>
            <p className="text-xs text-muted-foreground/60 mt-0.5 mb-2">Key-value pairs for authentication and other headers</p>
            <div className="space-y-1">
              {customHeaders.map((header, idx) => {
                const isSavedKey = savedHeaderKeys.includes(header.key);
                return (
                  <div key={idx} className="flex items-center gap-1.5">
                    <input
                      type="text"
                      value={header.key}
                      placeholder="Authorization"
                      onChange={(e) => {
                        const next = customHeaders.map((h, i) => (i === idx ? { ...h, key: e.target.value } : h));
                        setCustomHeaders(next);
                      }}
                      className="w-32 text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
                    />
                    <span className="text-muted-foreground/40 text-xs">=</span>
                    <input
                      type="text"
                      value={header.value}
                      placeholder={isSavedKey && !header.value ? "Header unchanged — enter new value to update" : "Bearer …"}
                      onChange={(e) => {
                        const next = customHeaders.map((h, i) => (i === idx ? { ...h, value: e.target.value } : h));
                        setCustomHeaders(next);
                      }}
                      className="flex-1 text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
                    />
                    <button
                      type="button"
                      onClick={() => setCustomHeaders(customHeaders.filter((_, i) => i !== idx))}
                      className="text-muted-foreground/40 hover:text-red-500 transition-colors p-0.5"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}
              <button
                type="button"
                onClick={() => setCustomHeaders([...customHeaders, { key: "", value: "" }])}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
              >
                + Add header
              </button>
            </div>
          </div>
        </div>
      ) : provider === "bedrock" ? (
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium text-foreground">AWS credentials</label>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Leave access key / secret blank to use the system AWS credential chain
              (env vars, <span className="font-mono">~/.aws/credentials</span>, IAM role).
            </p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">AWS region</label>
            <input
              type="text"
              value={awsRegion}
              onChange={(e) => setAwsRegion(e.target.value)}
              placeholder="us-west-2"
              className="w-full mt-1 bg-background border border-border rounded-xl px-4 py-2.5
                         text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                         focus:border-primary/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Access key ID</label>
            <input
              type="text"
              value={awsAccessKey}
              onChange={(e) => setAwsAccessKey(e.target.value)}
              placeholder={hasExistingAwsKeys ? "Stored — enter a new one to change" : "AKIA… (optional)"}
              className="w-full mt-1 bg-background border border-border rounded-xl px-4 py-2.5
                         text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                         focus:border-primary/50 placeholder:text-muted-foreground/30"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Secret access key</label>
            <div className="relative">
              <input
                type={showAwsSecret ? "text" : "password"}
                value={awsSecret}
                onChange={(e) => setAwsSecret(e.target.value)}
                placeholder={hasExistingAwsKeys ? "Stored — enter a new one to change" : "optional"}
                className="w-full mt-1 bg-background border border-border rounded-xl px-4 py-2.5
                           text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                           focus:border-primary/50 placeholder:text-muted-foreground/30 pr-11"
              />
              <button
                type="button"
                onClick={() => setShowAwsSecret((v) => !v)}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground"
              >
                {showAwsSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <details className="text-xs" open={showSessionToken || !!awsSessionToken}>
            <summary
              className="cursor-pointer text-muted-foreground/60 hover:text-muted-foreground select-none"
              onClick={() => setShowSessionToken((v) => !v)}
            >
              Session token (for temporary STS credentials)
            </summary>
            <input
              type="password"
              value={awsSessionToken}
              onChange={(e) => setAwsSessionToken(e.target.value)}
              placeholder="optional"
              className="w-full mt-2 bg-background border border-border rounded-xl px-4 py-2.5
                         text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/25
                         focus:border-primary/50 placeholder:text-muted-foreground/30"
            />
          </details>
        </div>
      ) : (
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
      )}

      {/* Prompt caching — only meaningful for Anthropic + Bedrock (Claude on
          Bedrock). Other providers ignore the marker. */}
      {(provider === "anthropic" || provider === "bedrock") && (
        <div className="space-y-2">
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={enablePromptCache}
              onChange={(e) => setEnablePromptCache(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-border accent-primary cursor-pointer"
            />
            <span className="flex-1">
              <span className="text-sm font-medium text-foreground">Enable prompt caching</span>
              <span className="block text-xs text-muted-foreground/60 mt-0.5">
                Cache the system prompt and tool definitions across requests. Reduces cost and latency
                {provider === "bedrock" && " on supported Bedrock regions and models"}.
              </span>
            </span>
          </label>
        </div>
      )}

      {/* Shared verification status + Verify button (Bedrock and openai-compatible
          get an explicit button since there's no single field to blur off of). */}
      <div className="space-y-2">
        {(provider === "bedrock" || provider === "openai-compatible") && (
          <button
            type="button"
            onClick={runKeyTest}
            disabled={keyStatus.state === "testing" || (provider === "openai-compatible" && !customUrl.trim())}
            className="text-sm px-4 py-2 rounded-lg border border-border
                       hover:bg-muted/50 transition-colors disabled:opacity-40"
          >
            {keyStatus.state === "testing" ? "Verifying…" : "Verify connection"}
          </button>
        )}
        {keyStatus.state === "testing" && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" /> Verifying…
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
        {saveStatus === "saved"  && <Check  className="w-4 h-4" strokeWidth={3} />}
        {saveStatus === "saved" ? "Saved!" : "Save"}
      </button>
    </div>
  );
}
