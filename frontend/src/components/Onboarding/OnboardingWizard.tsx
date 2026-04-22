import { useState, useRef, useEffect } from "react";
import { Check, Eye, EyeOff, Loader2, X } from "lucide-react";
import { saveDisplaySettings, saveLlmSettings, testLlmKey } from "@/api/settings";
import { useDisplayStore } from "@/store/display";

type Provider = "anthropic" | "openai" | "google";

interface WizardProps {
  onComplete: () => void;
  onDismiss: () => void;
}

// ─── Model options ─────────────────────────────────────────────────────────────

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
    { value: "gemini-2.0-flash",   label: "Gemini 2.0 Flash",   note: "Recommended" },
    { value: "gemini-1.5-pro",     label: "Gemini 1.5 Pro",     note: "Most capable"},
    { value: "gemini-1.5-flash",   label: "Gemini 1.5 Flash",   note: "Fastest"     },
  ],
};

// ─── Step 1 — warm inline sentence ────────────────────────────────────────────

const SAMPLE_NAMES = ["Aria", "Nova", "Scout", "Sage", "Atlas", "Ember", "Iris", "Max", "Luna", "Felix", "Analytics Agent", "Zara", "Rex"];

function Step1Name({ value, onChange, onSubmit }: { value: string; onChange: (v: string) => void; onSubmit: () => void }) {
  const measureRef = useRef<HTMLSpanElement>(null);
  const [inputWidth, setInputWidth] = useState(200);

  // Typewriter cycling state — only active while the user hasn't typed anything
  const [nameIdx, setNameIdx] = useState(0);
  const [charIdx, setCharIdx] = useState(0);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    if (value) return;
    const name = SAMPLE_NAMES[nameIdx];
    if (charIdx < name.length) {
      const t = setTimeout(() => setCharIdx(c => c + 1), 85);
      return () => clearTimeout(t);
    }
    // Fully typed — hold, then fade out and advance to next name
    const t = setTimeout(() => {
      setFading(true);
      setTimeout(() => {
        setNameIdx(i => (i + 1) % SAMPLE_NAMES.length);
        setCharIdx(0);
        setFading(false);
      }, 350);
    }, 1600);
    return () => clearTimeout(t);
  }, [charIdx, nameIdx, value]);

  const typedPlaceholder = value ? "" : SAMPLE_NAMES[nameIdx].slice(0, charIdx);

  // Width tracks whichever is wider: actual value or current placeholder
  useEffect(() => {
    if (measureRef.current) {
      setInputWidth(Math.max(measureRef.current.offsetWidth + 8, 80));
    }
  }, [value, typedPlaceholder]);

  return (
    <div className="flex flex-col justify-center h-full select-none">
      {/* Hidden measuring span */}
      <span
        ref={measureRef}
        aria-hidden
        className="absolute invisible whitespace-pre text-[2.6rem] font-light tracking-[-0.02em]"
      >
        {value || typedPlaceholder || "M"}
      </span>

      {/* The sentence */}
      <div className="text-[2.6rem] font-light tracking-[-0.02em] leading-[1.25] text-foreground">
        Hello! I'm{" "}
        <span
          className="relative"
          style={{ display: "inline-block", verticalAlign: "baseline", lineHeight: 1 }}
        >
          <input
            autoFocus
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onSubmit(); }}
            placeholder=""
            style={{ width: inputWidth, height: "1.15em", lineHeight: 1, padding: 0 }}
            className="inline bg-transparent outline-none border-b-2 border-primary/40
                       hover:border-primary/60 focus:border-primary
                       text-[2.6rem] font-light tracking-[-0.02em]
                       text-primary transition-colors duration-150 pb-0.5 block"
          />
          {/* Cycling typewriter placeholder — only visible when input is empty */}
          {!value && (
            <span
              aria-hidden
              className={`absolute inset-0 pointer-events-none whitespace-pre
                          text-[2.6rem] font-light tracking-[-0.02em] leading-none
                          text-muted-foreground/30 transition-opacity duration-300
                          ${fading ? "opacity-0" : "opacity-100"}`}
            >
              {typedPlaceholder}
            </span>
          )}
        </span>
        ,
      </div>
      <div className="text-[2.6rem] font-light tracking-[-0.02em] leading-[1.25] text-foreground">
        your data analytics agent.
      </div>

      <p className="mt-7 text-base text-muted-foreground/60 font-normal tracking-normal">
        What should I go by?
      </p>
    </div>
  );
}

// ─── Step 2 — model picker, Apple-feeling ──────────────────────────────────────

export type KeyStatus = { state: "idle" } | { state: "testing" } | { state: "ok"; msg: string } | { state: "fail"; msg: string };

function Step2Model({
  provider, onProvider,
  model,    onModel,
  apiKey,   onApiKey,
  keyStatus, onKeyBlur,
}: {
  provider: Provider;   onProvider: (p: Provider) => void;
  model: string;        onModel: (m: string) => void;
  apiKey: string;       onApiKey: (k: string) => void;
  keyStatus: KeyStatus; onKeyBlur: () => void;
}) {
  const [showKey, setShowKey] = useState(false);
  const models = MODELS[provider];

  const handleProvider = (p: Provider) => {
    onProvider(p);
    onModel(MODELS[p][1].value);
  };

  return (
    <div className="flex flex-col justify-center h-full max-w-lg">
      {/* Big intro sentence */}
      <div className="text-[2rem] font-light tracking-[-0.02em] leading-[1.3] text-foreground mb-10">
        Before we can get started, I'll need<br />
        to pick a model to think with.
      </div>

      {/* Provider segmented control */}
      <div className="flex rounded-xl border border-border p-1 gap-1 mb-7 w-fit">
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

      {/* Model radio list */}
      <div className="space-y-1 mb-8">
        {models.map((m) => {
          const active = model === m.value;
          return (
            <button
              key={m.value}
              type="button"
              onClick={() => onModel(m.value)}
              className={`w-full flex items-center gap-4 px-4 py-3 rounded-xl text-left
                transition-all duration-150 border
                ${active
                  ? "border-primary/30 bg-primary/[0.05]"
                  : "border-transparent hover:border-border hover:bg-muted/40"
                }`}
            >
              {/* Radio circle */}
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

      {/* API key */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-foreground">
          API key <span className="text-primary">*</span>
        </label>
        <div className="relative">
          <input
            type={showKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => onApiKey(e.target.value)}
            onBlur={onKeyBlur}
            placeholder={provider === "anthropic" ? "sk-ant-api03-…" : provider === "google" ? "AIza…" : "sk-proj-…"}
            className={`w-full bg-background border rounded-xl px-4 py-3 text-sm font-mono
              focus:outline-none focus:ring-2 focus:ring-primary/25
              placeholder:text-muted-foreground/30 transition-all pr-11
              ${keyStatus.state === "ok"   ? "border-emerald-500/50 focus:border-emerald-500/60"
              : keyStatus.state === "fail" ? "border-red-400/50 focus:border-red-400/60"
              : "border-border focus:border-primary/50"}`}
          />
          <button
            type="button"
            onClick={() => setShowKey(v => !v)}
            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground/40
                       hover:text-muted-foreground transition-colors"
          >
            {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>

        {/* Verification status */}
        {keyStatus.state === "testing" && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" />
            Verifying key…
          </p>
        )}
        {keyStatus.state === "ok" && (
          <p className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
            <Check className="w-3 h-3" strokeWidth={3} />
            {keyStatus.msg}
          </p>
        )}
        {keyStatus.state === "fail" && (
          <p className="flex items-center gap-1.5 text-xs text-red-500">
            <X className="w-3 h-3" strokeWidth={3} />
            {keyStatus.msg}
          </p>
        )}
        {keyStatus.state === "idle" && (
          <p className="text-xs text-muted-foreground/50">
            {provider === "anthropic"
              ? "console.anthropic.com/settings/api-keys"
              : provider === "google"
              ? "aistudio.google.com/app/apikey"
              : "platform.openai.com/api-keys"}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Step indicator ────────────────────────────────────────────────────────────

function StepNode({ index, current }: { index: number; current: number }) {
  const done = index < current;
  const active = index === current;
  const labels = ["Name your agent", "Choose a model"];
  return (
    <div className="flex items-start gap-3 relative">
      {index === 0 && (
        <div className="absolute left-[13px] top-7 w-px h-8 bg-border/60">
          <div className="w-full bg-primary transition-all duration-500"
               style={{ height: done ? "100%" : "0%" }} />
        </div>
      )}
      <div className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center
        text-xs font-bold transition-all duration-300 border-2
        ${done
          ? "bg-primary border-primary text-primary-foreground"
          : active
          ? "bg-background border-primary text-primary shadow-[0_0_0_4px_hsl(var(--primary)/0.12)]"
          : "bg-background border-border text-muted-foreground/50"}`}>
        {done ? <Check className="w-3.5 h-3.5" strokeWidth={3} /> : <span>{index + 1}</span>}
      </div>
      <span className={`pt-0.5 text-sm leading-tight transition-colors duration-200
        ${active ? "text-foreground font-semibold" : done ? "text-muted-foreground/60" : "text-muted-foreground/40"}`}>
        {labels[index]}
      </span>
    </div>
  );
}

// ─── Wizard shell ──────────────────────────────────────────────────────────────

export function OnboardingWizard({ onComplete, onDismiss }: WizardProps) {
  const { setDisplay } = useDisplayStore();

  const [agentName, setAgentName] = useState("");
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState(MODELS.anthropic[1].value);
  const [apiKey, setApiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<KeyStatus>({ state: "idle" });

  // Reset verification whenever the key or provider changes
  useEffect(() => { setKeyStatus({ state: "idle" }); }, [apiKey, provider]);

  const [step, setStep] = useState(0);
  const [animKey, setAnimKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const displayName = agentName.trim() || "Analytics Agent";
  const canContinue = step === 0 ? agentName.trim().length > 0 : apiKey.trim().length > 0 && keyStatus.state !== "fail";

  const navigate = (next: number) => {
    setError(null);
    setStep(next);
    setAnimKey(k => k + 1);
  };

  // Shared test runner — used by onBlur AND by handleContinue
  const runKeyTest = async (): Promise<boolean> => {
    if (!apiKey.trim()) return false;
    setKeyStatus({ state: "testing" });
    try {
      const result = await testLlmKey({ provider, api_key: apiKey.trim(), model });
      const next: KeyStatus = result.ok
        ? { state: "ok", msg: result.message }
        : { state: "fail", msg: result.message };
      setKeyStatus(next);
      return result.ok;
    } catch {
      setKeyStatus({ state: "fail", msg: "Can't reach the server to verify key" });
      return false;
    }
  };

  const handleContinue = async () => {
    setError(null);
    setSaving(true);
    try {
      if (step === 0) {
        await saveDisplaySettings({ app_name: displayName, logo_url: "" });
        setDisplay(displayName, "");
        navigate(1);
      } else {
        // Always verify before saving — covers the case where user never blurred the field
        if (keyStatus.state !== "ok") {
          const ok = await runKeyTest();
          if (!ok) return;
        }
        await saveLlmSettings({ provider, api_key: apiKey.trim(), model });
        onComplete();
      }
    } catch (e) {
      const raw = String(e);
      if (raw.includes("Failed to fetch") || raw.includes("NetworkError") || raw.includes("ERR_CONNECTION")) {
        setError("Can't reach the server — make sure the backend is running.");
      } else {
        setError(raw.replace(/^(TypeError|Error):\s*/i, ""));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex bg-background">

      {/* ── Left panel ── */}
      <div className="onboarding-left w-[260px] xl:w-[300px] flex-shrink-0 border-r border-border
                      flex flex-col relative overflow-hidden">

        {/* Step number watermark */}
        <div className="absolute right-0 bottom-0 text-[200px] font-black leading-none
                        select-none pointer-events-none translate-x-8 translate-y-6
                        transition-all duration-500"
             style={{ color: "hsl(var(--primary) / 0.07)" }}>
          {String(step + 1).padStart(2, "0")}
        </div>

        {/* Logo */}
        <div className="px-8 pt-10 pb-8 flex items-center gap-2.5">
          <svg width="26" height="26" viewBox="0 0 64 64" fill="none" aria-hidden>
            <path d="M8 42 A30 30 0 0 1 52 10" stroke="#0078D4" strokeWidth="7" strokeLinecap="round"/>
            <path d="M56 42 A30 30 0 0 0 12 10" stroke="#E8A030" strokeWidth="7" strokeLinecap="round"/>
            <circle cx="24" cy="28" r="3.5" fill="#D44B20"/>
            <circle cx="32" cy="28" r="3.5" fill="#D44B20"/>
            <circle cx="40" cy="28" r="3.5" fill="#D44B20"/>
            <path d="M8 42 L3 54 L17 45" stroke="#0078D4" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M56 42 L61 54 L47 45" stroke="#E8A030" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          <span className="text-sm font-semibold tracking-tight">
            {step > 0 && agentName.trim() ? agentName.trim() : "Setup"}
          </span>
        </div>

        {/* Steps */}
        <div className="flex-1 px-8 space-y-5">
          <StepNode index={0} current={step} />
          <StepNode index={1} current={step} />
        </div>

        {/* Skip */}
        <div className="px-8 pb-8">
          <button onClick={onDismiss}
            className="text-xs text-muted-foreground/35 hover:text-muted-foreground/60 transition-colors">
            Skip setup
          </button>
        </div>
      </div>

      {/* ── Right panel ── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Progress bar */}
        <div className="h-[2px] bg-border/30 flex-shrink-0">
          <div className="h-full bg-primary transition-all duration-600 ease-out"
               style={{ width: step === 0 ? "0%" : "100%" }} />
        </div>

        {/* Content — full height, padding handles centering */}
        <div key={animKey}
             className="flex-1 overflow-y-auto px-16 xl:px-24 py-16 ob-enter-fwd">
          {step === 0 && <Step1Name value={agentName} onChange={setAgentName} onSubmit={handleContinue} />}
          {step === 1 && (
            <Step2Model
              provider={provider} onProvider={setProvider}
              model={model}       onModel={setModel}
              apiKey={apiKey}     onApiKey={setApiKey}
              keyStatus={keyStatus} onKeyBlur={runKeyTest}
            />
          )}
          {error && (
            <p className="mt-6 text-sm text-red-500 bg-red-500/8 border border-red-500/20
                          rounded-xl px-4 py-3 max-w-md">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-border/40 px-16 xl:px-24 py-5
                        flex items-center justify-between">
          <div>
            {step > 0 && (
              <button type="button" onClick={() => navigate(0)} disabled={saving}
                className="text-sm px-4 py-2 rounded-lg border border-border
                           hover:bg-muted/50 transition-colors disabled:opacity-40">
                Back
              </button>
            )}
          </div>
          <div className="flex items-center gap-4">
            {step === 1 && (
              <p className="text-xs text-muted-foreground/50 max-w-[240px] text-right leading-relaxed hidden xl:block">
                You'll connect DataHub and data<br />sources in the next screen.
              </p>
            )}
            <button
              type="button"
              onClick={handleContinue}
              disabled={saving || !canContinue}
              className="flex items-center gap-2 text-sm px-7 py-2.5 rounded-xl font-medium
                         bg-primary text-primary-foreground hover:bg-primary/90
                         transition-colors disabled:opacity-40"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              {step === 0 ? "Continue" : "Go to Connections →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
