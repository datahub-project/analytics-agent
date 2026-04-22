import { Database, Layers, Plus, Server, Zap } from "lucide-react";
import type { ConnectionCategory, ConnectionPlugin, ConnectionTransport } from "./types";

const TRANSPORT_BADGE: Record<ConnectionTransport, { label: string; cls: string }> = {
  native:     { label: "Native",    cls: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
  "mcp-stdio":{ label: "MCP stdio", cls: "bg-violet-500/10 text-violet-600 dark:text-violet-400" },
  "mcp-sse":  { label: "MCP SSE",   cls: "bg-violet-500/10 text-violet-600 dark:text-violet-400" },
};

function defaultIcon(plugin: ConnectionPlugin) {
  if (plugin.transport !== "native") return <Zap className="w-4 h-4" />;
  if (plugin.category === "context_platform") return <Layers className="w-4 h-4" />;
  return <Database className="w-4 h-4" />;
}

function PluginCard({
  plugin,
  onSelect,
}: {
  plugin: ConnectionPlugin;
  onSelect: (p: ConnectionPlugin) => void;
}) {
  const badge = TRANSPORT_BADGE[plugin.transport];
  return (
    <button
      type="button"
      onClick={() => onSelect(plugin)}
      className="w-full text-left flex items-start gap-3 px-3 py-2.5 rounded-lg border border-border/60 hover:border-primary/40 hover:bg-primary/[0.03] transition-all group"
    >
      <span className="mt-0.5 text-muted-foreground group-hover:text-primary transition-colors flex-shrink-0">
        {plugin.icon ?? defaultIcon(plugin)}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-medium text-foreground">{plugin.label}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${badge.cls}`}>
            {badge.label}
          </span>
        </div>
        <p className="text-xs text-muted-foreground/70 mt-0.5 leading-snug">{plugin.description}</p>
      </div>
    </button>
  );
}

export function TypePicker({
  plugins,
  category,
  onSelect,
  onCancel,
}: {
  plugins: ConnectionPlugin[];
  category: ConnectionCategory;
  onSelect: (p: ConnectionPlugin) => void;
  onCancel: () => void;
}) {
  const filtered = plugins.filter((p) => p.category === category);

  // Group by serviceId, preserving order of first appearance
  const order: string[] = [];
  const grouped: Record<string, ConnectionPlugin[]> = {};
  for (const p of filtered) {
    if (!grouped[p.serviceId]) {
      grouped[p.serviceId] = [];
      order.push(p.serviceId);
    }
    grouped[p.serviceId].push(p);
  }

  // Custom MCP wildcard always goes last
  const sorted = order.sort((a, b) => {
    if (a === "mcp-custom") return 1;
    if (b === "mcp-custom") return -1;
    return 0;
  });

  const categoryLabel = category === "engine" ? "Data Source" : "Context Platform";
  const Icon = category === "engine" ? Database : Layers;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 pb-1 border-b border-border/40">
        <Icon className="w-3.5 h-3.5 text-muted-foreground" />
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Add {categoryLabel}
        </p>
      </div>

      <div className="space-y-1">
        {sorted.map((serviceId) => {
          const group = grouped[serviceId];
          if (group.length === 1) {
            return <PluginCard key={group[0].id} plugin={group[0]} onSelect={onSelect} />;
          }
          // Multiple transports for the same service — show as sub-group
          return (
            <div key={serviceId} className="space-y-0.5">
              {group.map((p) => (
                <PluginCard key={p.id} plugin={p} onSelect={onSelect} />
              ))}
            </div>
          );
        })}
      </div>

      {/* Generic MCP escape hatch always shown as a distinct "bring your own" section */}
      <div className="pt-2 border-t border-border/40">
        <p className="text-xs text-muted-foreground/50 mb-1.5 flex items-center gap-1.5">
          <Server className="w-3 h-3" /> Any MCP server
        </p>
        {filtered
          .filter((p) => p.serviceId === "mcp-custom")
          .map((p) => (
            <PluginCard key={p.id} plugin={p} onSelect={onSelect} />
          ))}
      </div>

      <div className="flex justify-end pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
