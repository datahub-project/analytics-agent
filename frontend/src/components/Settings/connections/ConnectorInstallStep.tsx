import { useEffect, useState } from "react";
import { CheckCircle2, Download, Loader2, Package } from "lucide-react";
import { getConnectorStatus, installConnector } from "@/api/settings";

type Phase = "checking" | "installed" | "needs_install" | "installing" | "error";

export function ConnectorInstallStep({
  connectorType,
  packageName,
  onReady,
  onCancel,
}: {
  connectorType: string;
  packageName: string;
  /** Called once the connector is confirmed installed — proceed to the config form. */
  onReady: () => void;
  onCancel: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [error, setError] = useState("");

  useEffect(() => {
    getConnectorStatus(connectorType)
      .then((s) => {
        if (s.installed) {
          onReady(); // fast path — already installed, skip this step entirely
        } else {
          setPhase("needs_install");
        }
      })
      .catch(() => setPhase("needs_install")); // treat check failure as needing install
  }, [connectorType, onReady]);

  const handleInstall = async () => {
    setPhase("installing");
    setError("");
    try {
      await installConnector(connectorType);
      setPhase("installed");
      setTimeout(onReady, 800); // brief success flash before proceeding
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Installation failed.");
      setPhase("error");
    }
  };

  if (phase === "checking") {
    return (
      <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Checking connector…
      </div>
    );
  }

  if (phase === "installed") {
    return (
      <div className="flex items-center gap-2 py-4 text-xs text-green-600">
        <CheckCircle2 className="w-3.5 h-3.5" />
        Connector installed — continuing…
      </div>
    );
  }

  if (phase === "installing") {
    return (
      <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Installing <code className="font-mono">{packageName}</code>… this may take a minute.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2.5">
        <Package className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
        <div className="text-xs text-muted-foreground">
          <p className="font-medium text-foreground mb-1">Connector package required</p>
          <p>
            <code className="font-mono bg-muted px-1 py-0.5 rounded text-[11px]">{packageName}</code>{" "}
            runs in an isolated environment and is installed once.
          </p>
        </div>
      </div>

      {phase === "error" && (
        <p className="text-xs text-destructive bg-destructive/10 px-3 py-2 rounded">{error}</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleInstall}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Download className="w-3.5 h-3.5" />
          {phase === "error" ? "Retry install" : "Install connector"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs px-3 py-1.5 rounded border border-border text-muted-foreground hover:bg-muted/50 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
