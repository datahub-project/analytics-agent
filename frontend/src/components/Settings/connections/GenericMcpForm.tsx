import { useState } from "react";
import { Loader2 } from "lucide-react";
import type { NewConnectionPayload } from "./types";
import { ArrayField } from "./fields/ArrayField";
import { KeyValueField } from "./fields/KeyValueField";

type Pair = { key: string; value: string };

export function GenericMcpForm({
  onDone,
  onCancel,
}: {
  onDone: (payload: NewConnectionPayload) => void;
  onCancel: () => void;
}) {
  const [transport, setTransport] = useState<"stdio" | "sse" | "http">("stdio");
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");

  // stdio fields
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState<string[]>([]);
  const [env, setEnv] = useState<Pair[]>([]);

  // sse fields
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState<Pair[]>([]);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave =
    name.trim().length > 0 &&
    (transport === "stdio" ? command.trim().length > 0 : url.trim().length > 0);

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const mcpConfig =
        transport === "stdio"
          ? {
              transport: "stdio" as const,
              command: command.trim(),
              args: args.filter(Boolean),
              env: Object.fromEntries(env.filter((p) => p.key).map((p) => [p.key, p.value])),
            }
          : transport === "sse"
          ? {
              transport: "sse" as const,
              url: url.trim(),
              headers: Object.fromEntries(
                headers.filter((p) => p.key).map((p) => [p.key, p.value])
              ),
            }
          : {
              transport: "http" as const,
              url: url.trim(),
              headers: Object.fromEntries(
                headers.filter((p) => p.key).map((p) => [p.key, p.value])
              ),
            };
      await onDone({
        name: name.trim(),
        label: label.trim() || undefined,
        config: {},
        mcpConfig,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Transport selector */}
      <div className="flex gap-2">
        {(["stdio", "sse", "http"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTransport(t)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              transport === t
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
            }`}
          >
            {t === "stdio"
              ? "Local process (stdio)"
              : t === "sse"
              ? "Remote server (SSE)"
              : "Remote server (HTTP)"}
          </button>
        ))}
      </div>

      {/* stdio config */}
      {transport === "stdio" && (
        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">
              Command <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="npx"
              className="w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>
          <ArrayField
            label="Arguments"
            values={args}
            onChange={setArgs}
            placeholder="--arg"
            hint="one per line"
          />
          <KeyValueField
            label="Environment variables"
            pairs={env}
            onChange={setEnv}
            keyPlaceholder="API_KEY"
            valuePlaceholder="value"
          />
        </div>
      )}

      {/* remote config */}
      {(transport === "sse" || transport === "http") && (
        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">
              Server URL <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={transport === "sse" ? "https://mcp.example.com/sse" : "https://mcp.example.com/mcp"}
              className="w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
          </div>
          <KeyValueField
            label="Headers"
            pairs={headers}
            onChange={setHeaders}
            keyPlaceholder="Authorization"
            valuePlaceholder="Bearer …"
          />
        </div>
      )}

      {/* Identity */}
      <div className="border-t border-border/40 pt-3 grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-mcp-server"
            className="w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Label</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Display label (optional)"
            className="w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !canSave}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Save
        </button>
      </div>
    </div>
  );
}
