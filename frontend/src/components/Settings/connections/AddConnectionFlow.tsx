import { useState } from "react";
import { Plus } from "lucide-react";
import type { ConnectionCategory, ConnectionPlugin, NewConnectionPayload } from "./types";
import { CONNECTION_PLUGINS } from "./index";
import { TypePicker } from "./TypePicker";
import { ConnectorInstallStep } from "./ConnectorInstallStep";

type Step = "picker" | "install" | "form";

export function AddConnectionFlow({
  category,
  onDone,
  buttonLabel,
}: {
  category: ConnectionCategory;
  /** Called after the plugin form completes. Host is responsible for calling createConnection(). */
  onDone: (payload: NewConnectionPayload, plugin: ConnectionPlugin) => Promise<void>;
  buttonLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [activePlugin, setActivePlugin] = useState<ConnectionPlugin | null>(null);
  const [step, setStep] = useState<Step>("picker");

  const reset = () => {
    setOpen(false);
    setActivePlugin(null);
    setStep("picker");
  };

  const handlePluginSelect = (plugin: ConnectionPlugin) => {
    setActivePlugin(plugin);
    // Native transport connectors run as MCP subprocesses — check/install first.
    setStep(plugin.transport === "native" ? "install" : "form");
  };

  const handleDone = async (payload: NewConnectionPayload) => {
    if (!activePlugin) return;
    await onDone(payload, activePlugin);
    reset();
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-dashed border-border text-muted-foreground hover:border-primary/40 hover:text-primary hover:bg-primary/5 transition-colors"
      >
        <Plus className="w-3.5 h-3.5" />
        {buttonLabel ?? "Add connection"}
      </button>
    );
  }

  return (
    <div className="border border-border rounded-lg p-4 mt-1">
      {step === "picker" && (
        <TypePicker
          plugins={CONNECTION_PLUGINS}
          category={category}
          onSelect={handlePluginSelect}
          onCancel={reset}
        />
      )}
      {step === "install" && activePlugin && (
        <>
          <p className="text-xs font-medium mb-3 text-foreground">{activePlugin.label}</p>
          <ConnectorInstallStep
            connectorType={activePlugin.id}
            packageName={`analytics-agent-connector-${activePlugin.id}`}
            onReady={() => setStep("form")}
            onCancel={reset}
          />
        </>
      )}
      {step === "form" && activePlugin && (
        <>
          <p className="text-xs font-medium mb-3 text-foreground">{activePlugin.label}</p>
          <activePlugin.Form onDone={handleDone} onCancel={reset} />
        </>
      )}
    </div>
  );
}
