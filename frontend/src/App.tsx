import { useEffect, useState } from "react";
import { useThemeStore } from "@/store/theme";
import { Settings } from "lucide-react";
import { listConversations, listEngines } from "@/api/conversations";
import { getDisplaySettings, getLlmSettings } from "@/api/settings";
import { useConversationsStore } from "@/store/conversations";
import { useDisplayStore } from "@/store/display";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { ChatView } from "@/components/Chat/ChatView";
import { SettingsModal } from "@/components/Settings/SettingsModal";
import { OnboardingWizard } from "@/components/Onboarding/OnboardingWizard";

// Captured before any effects run — the hash effect clears it immediately,
// so the LLM-settings effect would see an empty hash otherwise.
const FORCE_SETUP = window.location.hash === "#setup";

export default function App() {
  const { setConversations, setEngines } = useConversationsStore();
  const { setDisplay } = useDisplayStore();
  const { theme } = useThemeStore();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Keep browser tab title in sync with the configured agent name
  const { appName } = useDisplayStore();
  useEffect(() => {
    document.title = appName || "Analytics Agent";
  }, [appName]);

  const [showSettings, setShowSettings] = useState(false);
  // null = still checking; true = show; false = don't show
  const [showOnboarding, setShowOnboarding] = useState<boolean | null>(
    FORCE_SETUP ? true : null
  );

  // #setup hash — works on mount AND when typed into the address bar while app is open
  useEffect(() => {
    if (FORCE_SETUP) {
      history.replaceState(null, "", window.location.pathname);
      localStorage.removeItem("onboarding_dismissed");
    }

    const onHash = () => {
      if (window.location.hash === "#setup") {
        history.replaceState(null, "", window.location.pathname);
        localStorage.removeItem("onboarding_dismissed");
        setShowSettings(false);
        setShowOnboarding(true);
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    listConversations().then(setConversations).catch(console.error);
    listEngines().then(setEngines).catch(console.error);
    getDisplaySettings()
      .then((d) => setDisplay(d.app_name, d.logo_url))
      .catch(() => {});

    // Skip the has_key check when #setup forced the wizard open
    if (FORCE_SETUP) return;

    const dismissed = localStorage.getItem("onboarding_dismissed") === "1";
    if (dismissed) {
      setShowOnboarding(false);
    } else {
      getLlmSettings()
        .then((s) => setShowOnboarding(!s.has_key))
        .catch(() => setShowOnboarding(false));
    }
  }, []);

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center justify-end px-4 py-2 border-b border-border/40" data-print-hide>
          <button
            onClick={() => setShowSettings(true)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground
                       px-2.5 py-1.5 rounded-md hover:bg-muted/60 transition-colors"
            title="Settings"
          >
            <Settings className="w-3.5 h-3.5" />
            Settings
          </button>
        </div>
        <ChatView />
      </main>

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}

      {showOnboarding === true && (
        <OnboardingWizard
          onComplete={() => {
            setShowOnboarding(false);
            setShowSettings(true); // land straight in Settings → Connections
          }}
          onDismiss={() => {
            localStorage.setItem("onboarding_dismissed", "1");
            setShowOnboarding(false);
          }}
        />
      )}
    </div>
  );
}
