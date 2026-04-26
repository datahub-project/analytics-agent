import { useState, useRef, useEffect, useMemo, type KeyboardEvent } from "react";
import { Send, Database } from "lucide-react";
import { useConversationsStore } from "@/store/conversations";
import { useDisplayStore, GREETING_TTL_MS } from "@/store/display";
import { createConversation } from "@/api/conversations";
import { STARTER_PROMPTS } from "@/lib/starterPrompts";

async function fetchDataHubUser(): Promise<string> {
  try {
    const res = await fetch("/api/me");
    if (!res.ok) return "";
    const data = await res.json();
    return data.display_name || data.username || "";
  } catch {
    return "";
  }
}

function getTimeOfDay(): string {
  const h = new Date().getHours();
  if (h < 12) return "morning";
  if (h < 17) return "afternoon";
  return "evening";
}

// Module-level flag prevents double-fetch from React StrictMode / remounts
let _greetingFetchInFlight = false;

async function fetchLlmGreeting(name: string): Promise<string> {
  try {
    const params = new URLSearchParams({ name, time_of_day: getTimeOfDay() });
    const res = await fetch(`/api/greeting?${params}`);
    if (!res.ok) return "";
    const data = await res.json();
    return data.greeting || "";
  } catch {
    return "";
  }
}

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function pickSuggestions(n: number): string[] {
  const shuffled = [...STARTER_PROMPTS].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, n);
}

interface Props {
  onSend: (text: string, engineName: string) => void;
}

export function WelcomeView({ onSend }: Props) {
  const { engines } = useConversationsStore();
  const { appName, logoUrl } = useDisplayStore();
  const [text, setText] = useState("");
  const [placeholder, ...suggestions] = useMemo(() => pickSuggestions(5), []);
  const [engine, setEngine] = useState(engines[0]?.name ?? "");
  const { greeting: cachedGreeting, userName: cachedUser, greetingGeneratedAt, setGreeting: storeGreeting } = useDisplayStore();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Use cached values from store; only call APIs once per session
  const userName = cachedUser;
  const greeting = cachedGreeting;

  useEffect(() => {
    if (!engine && engines.length > 0) setEngine(engines[0].name);
  }, [engines]);

  useEffect(() => {
    const stale = Date.now() - greetingGeneratedAt > GREETING_TTL_MS;
    if ((cachedGreeting && !stale) || _greetingFetchInFlight) return;
    _greetingFetchInFlight = true;
    fetchDataHubUser().then((name) => {
      fetchLlmGreeting(name).then((g) => {
        storeGreeting(g, name);
        _greetingFetchInFlight = false;
      });
    });
  }, []);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed, engine);
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-8 px-4 pb-16">
      {/* Greeting */}
      <div className="flex flex-col items-center gap-3 select-none">
        {logoUrl ? (
          <img src={logoUrl} alt="Logo" className="w-12 h-12 object-contain" />
        ) : (
          <svg width="48" height="48" viewBox="0 0 64 64" fill="none" aria-hidden>
            <path d="M8 42 A30 30 0 0 1 52 10" stroke="#0078D4" strokeWidth="7" strokeLinecap="round"/>
            <path d="M56 42 A30 30 0 0 0 12 10" stroke="#E8A030" strokeWidth="7" strokeLinecap="round"/>
            <circle cx="24" cy="28" r="3.5" fill="#D44B20"/>
            <circle cx="32" cy="28" r="3.5" fill="#D44B20"/>
            <circle cx="40" cy="28" r="3.5" fill="#D44B20"/>
            <path d="M8 42 L3 54 L17 45" stroke="#0078D4" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M56 42 L61 54 L47 45" stroke="#E8A030" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-center max-w-lg leading-snug min-h-[2rem]">
          {greeting ? (
            greeting
          ) : (
            <span className="inline-block w-48 h-7 rounded-md bg-muted animate-pulse" />
          )}
        </h1>
      </div>

      {/* Input card */}
      <div className="w-full max-w-2xl">
        <div className="rounded-2xl border border-border bg-background shadow-sm focus-within:shadow-md focus-within:border-border transition-shadow">
          {/* Textarea */}
          <div className="px-4 pt-3 pb-2">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              onInput={handleInput}
              placeholder={placeholder}
              rows={1}
              className="w-full bg-transparent resize-none outline-none text-sm placeholder:text-muted-foreground/50 max-h-40 leading-relaxed"
            />
          </div>

          {/* Toolbar */}
          <div className="flex items-center justify-between px-3 pb-3">
            {/* Engine selector */}
            {engines.length > 0 && (
              <div className="flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5 text-muted-foreground" />
                <select
                  value={engine}
                  onChange={(e) => setEngine(e.target.value)}
                  className="text-xs bg-transparent border border-border rounded px-2 py-1 text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                >
                  {engines.map((e) => (
                    <option key={e.name} value={e.name}>{e.name}</option>
                  ))}
                </select>
              </div>
            )}
            {engines.length === 0 && <span />}

            {/* Send */}
            <button
              onClick={handleSend}
              disabled={!text.trim()}
              className="p-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90
                         disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Suggestion chips */}
        {engines.length > 0 && (
          <div className="grid grid-cols-2 gap-2 mt-3 w-full max-w-2xl">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setText(s);
                  textareaRef.current?.focus();
                }}
                className="text-xs px-3 py-2 rounded-xl border border-border bg-muted/30
                           hover:bg-muted/60 text-muted-foreground hover:text-foreground
                           transition-colors text-left leading-snug"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
