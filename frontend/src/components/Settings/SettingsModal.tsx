import { useEffect, useRef, useState, useCallback } from "react";
import {
  X,
  Database,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  Loader2,
  Save,
  FlaskConical,
  Link2,
  BarChart3,
  Settings2,
  FileText,
  Monitor,
  Cpu,
  RotateCcw,
  Wrench,
  LogIn,
  LogOut,
  KeyRound,
  Lock,
  Trash2,
  Plus,
  Layers,
  BookOpen,
  Pencil,
  Info,
} from "lucide-react";
import {
  listConnections,
  testConnection,
  saveConnection,
  splitConnectionValues,
  patchConnectionLabel,
  updateConnectionTools,
  createConnection,
  deleteConnection,
  fetchDataHubCapabilities,
  getPrompt,
  savePrompt,
  resetPrompt,
  getDisplaySettings,
  saveDisplaySettings,
  fetchDataHubCoverage,
  type Connection,
  type ConnectionField,
  type DataHubCoverageResponse,
  type DataHubCheckResult,
  type TestConnectionResult,
  type ToolToggle,
} from "@/api/settings";
import {
  browserSso,
  parseSnowflakeAccount,
  initiateOAuthFlow,
  disconnectOAuth,
  saveOAuthAppConfig,
  removeOAuthApp,
  saveSnowflakePat,
} from "@/api/oauth";
import { SnowflakeAuthSection } from "./SnowflakeAuthSection";
import { DataHubBadge } from "@/components/Brand/DataHubBadge";
import { ThemeSwitcher } from "@/components/Brand/ThemeSwitcher";
import { useDisplayStore } from "@/store/display";
import { useConversationsStore } from "@/store/conversations";
import { useConnectionSettingsStore } from "@/store/connectionSettings";
import { listEngines } from "@/api/conversations";
import { AddConnectionFlow } from "./connections/AddConnectionFlow";
import type { NewConnectionPayload, ConnectionPlugin } from "./connections/types";
import { ModelSection } from "./ModelSection";
import { AboutSection } from "./AboutSection";

type Section = "connections" | "model" | "prompt" | "display" | "about";

interface Props {
  onClose: () => void;
  /** When true the About nav item shows an update-available badge. */
  updateAvailable?: boolean;
}

// --- Status badge ---

function StatusBadge({ status }: { status: Connection["status"] }) {
  if (status === "connected")
    return (
      <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
        </span>
        Connected
      </span>
    );
  if (status === "error")
    return (
      <span className="flex items-center gap-1.5 text-xs font-medium text-red-500">
        <AlertCircle className="w-3 h-3" />
        Error
      </span>
    );
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium text-amber-500">
      <Clock className="w-3 h-3" />
      Unconfigured
    </span>
  );
}

// --- Field row ---

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: ConnectionField;
  value: string;
  onChange: (v: string) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const isMasked = field.sensitive && value.includes("•");

  return (
    <div className="grid grid-cols-[140px_1fr] items-center gap-3">
      <label className="text-xs text-muted-foreground text-right leading-tight">
        {field.label}
      </label>
      <div className="relative">
        <input
          type={field.sensitive && !revealed ? "password" : "text"}
          value={isMasked ? "" : value}
          placeholder={isMasked ? "unchanged — enter new value to update" : field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 pr-8
                     focus:outline-none focus:ring-1 focus:ring-primary/50
                     placeholder:text-muted-foreground/40 font-mono"
        />
        {field.sensitive && (
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground"
          >
            {revealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>
    </div>
  );
}

// --- Tool toggle row ---

function ToolToggleRow({
  tool,
  enabled,
  onToggle,
  saving,
}: {
  tool: ToolToggle;
  enabled: boolean;
  onToggle: () => void;
  saving: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span
        className="text-xs text-muted-foreground font-mono"
        title={tool.description || undefined}
      >
        {tool.label}
      </span>
      <button
        onClick={onToggle}
        disabled={saving}
        className={`relative inline-flex h-4 w-8 flex-shrink-0 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
          enabled ? "bg-primary" : "bg-muted-foreground/30"
        }`}
        role="switch"
        aria-checked={enabled}
      >
        <span
          className={`inline-block h-3 w-3 rounded-full bg-white shadow transform transition-transform duration-200 mt-0.5 ${
            enabled ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

const OAUTH_SUPPORTED = new Set(["snowflake"]);

// --- DataHub coverage badge (shown on engine cards) ---

const MUTATION_TOOL_NAMES = new Set(["publish_analysis", "save_correction"]);

function DataHubCoverageBadge({ engineName }: { engineName: string }) {
  const [coverage, setCoverage] = useState<DataHubCoverageResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDataHubCoverage(engineName)
      .then(setCoverage)
      .catch(() => setCoverage({ covered: false, dataset_count: 0 }))
      .finally(() => setLoading(false));
  }, [engineName]);

  if (loading) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/40 animate-pulse">
        <Link2 className="w-3 h-3" /> Checking DataHub…
      </span>
    );
  }

  if (!coverage || (!coverage.covered && coverage.dataset_count === 0)) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/50">
        <Link2 className="w-3 h-3" /> Not indexed in DataHub
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium">
      <Link2 className="w-3 h-3" />
      {coverage.dataset_count.toLocaleString()} dataset{coverage.dataset_count !== 1 ? "s" : ""} in DataHub
    </span>
  );
}

// --- DataHub card (Context Platform section) ---

function DataHubCard({
  connection,
  disabledTools,
  enabledMutations,
  disabledConnections,
  onToolToggle,
  onMutationToggle,
  onGlobalToggle,
  toolSaving,
  onOAuthChange,
  onDelete,
  discovering = false,
}: {
  connection: Connection;
  disabledTools: Set<string>;
  enabledMutations: Set<string>;
  disabledConnections: Set<string>;
  onToolToggle: (toolName: string, currentlyEnabled: boolean, connection: Connection) => void;
  onMutationToggle: (name: string, currentlyEnabled: boolean, connection: Connection) => void;
  onGlobalToggle: (enable: boolean, connection: Connection) => void;
  toolSaving: boolean;
  onOAuthChange: () => void;
  onDelete?: (name: string) => void;
  discovering?: boolean;
}) {
  const [configExpanded, setConfigExpanded] = useState(false);
  // Auto-expand when tool discovery starts so the skeleton is visible
  const prevDiscovering = useRef(discovering);
  useEffect(() => {
    if (discovering && !prevDiscovering.current) setConfigExpanded(true);
    prevDiscovering.current = discovering;
  }, [discovering]);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(connection.fields.map((f) => [f.key, f.value]))
  );
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const [mutationWarningDismissed, setMutationWarningDismissed] = useState(
    () => localStorage.getItem("dh_mutation_warning_dismissed") === "1"
  );
  const [semanticSearch, setSemanticSearch] = useState<boolean | null>(null);

  useEffect(() => {
    if (connection.status === "connected") {
      fetchDataHubCapabilities().then((caps) => setSemanticSearch(caps.semantic_search));
    }
  }, [connection.status]);

  const isMutationTool = (name: string) =>
    connection.type?.includes("mcp")
      ? /^(add|remove|set|update|delete|create|save|publish|write|upsert|insert|patch)_/i.test(name)
      : MUTATION_TOOL_NAMES.has(name);
  const readTools = (connection.tools ?? []).filter((t) => !isMutationTool(t.name));
  const mutationTools = (connection.tools ?? []).filter((t) => isMutationTool(t.name));
  // Master toggle: driven by disabledConnections, not individual tool state
  const contextEnabled = !disabledConnections.has(connection.name);

  const enabledReadCount = contextEnabled
    ? readTools.filter((t) => t.enabled).length
    : 0;
  const enabledMutationCount = contextEnabled
    ? mutationTools.filter((t) => enabledMutations.has(t.name)).length
    : 0;
  const anyMutationEnabled = contextEnabled && mutationTools.some((t) => enabledMutations.has(t.name));

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      const result = await testConnection(connection.name);
      setTestResult(result);
      // If tools were just discovered, refresh so the tool toggles appear
      if (result.success && connection.type?.includes("mcp")) onOAuthChange();
    }
    catch (e) { setTestResult({ success: false, error: String(e) }); }
    finally { setTesting(false); }
  };

  const handleSave = async () => {
    setSaving(true); setSaveResult(null);
    try {
      const body = splitConnectionValues(connection.fields, values);
      const r = await saveConnection(connection.name, body);
      setSaveResult(r.message);
    }
    catch (e) { setSaveResult("Save failed: " + String(e)); }
    finally { setSaving(false); }
  };

  const handleDismissWarning = () => {
    localStorage.setItem("dh_mutation_warning_dismissed", "1");
    setMutationWarningDismissed(true);
  };

  return (
    <div className="border-2 border-primary/20 rounded-lg overflow-hidden bg-primary/[0.02]">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="w-1 h-8 rounded-full flex-shrink-0 bg-primary" />
        <Layers className="w-4 h-4 text-primary flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">{connection.label}</p>
          {(() => {
            const url = connection.fields.find((f) => f.key === "url")?.value;
            return url
              ? <p className="text-xs text-muted-foreground font-mono truncate" title={url}>{url}</p>
              : <p className="text-xs text-muted-foreground">metadata &amp; governance</p>;
          })()}
        </div>
        <StatusBadge status={connection.status} />
        {connection.source === "ui" && onDelete && (
          <button
            onClick={() => onDelete(connection.name)}
            className="text-muted-foreground hover:text-red-500 transition-colors p-0.5 rounded"
            title="Delete connection"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
        <button
          onClick={() => onGlobalToggle(!contextEnabled, connection)}
          disabled={toolSaving}
          title={contextEnabled ? "Disable all DataHub tools" : "Enable all DataHub tools"}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
            contextEnabled ? "bg-primary" : "bg-muted-foreground/30"
          }`}
          role="switch"
          aria-checked={contextEnabled}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200 mt-0.5 ${
              contextEnabled ? "translate-x-4" : "translate-x-0.5"
            }`}
          />
        </button>
      </div>

      {/* Semantic search capability warning */}
      {semanticSearch === false && connection.status === "connected" && (
        <div
          className="mx-4 mb-1 flex items-center gap-2 text-xs px-2.5 py-2 rounded"
          style={{
            backgroundColor: "hsl(var(--quality-fair) / 0.12)",
            borderWidth: 1,
            borderStyle: "solid",
            borderColor: "hsl(var(--quality-fair) / 0.35)",
            color: `hsl(var(--quality-fair))`,
          }}
        >
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>Semantic search not available — context retrieval quality may be degraded</span>
        </div>
      )}

{/* Tool groups — dim/freeze when global context is off */}
      <div className={`px-4 pb-4 space-y-2 transition-opacity duration-200 ${!contextEnabled ? "opacity-40 pointer-events-none" : ""}`}>
        {/* MCP: skeleton while discovering, static hint once idle with no tools */}
        {readTools.length === 0 && connection.type?.includes("mcp") && (
          discovering ? (
            <div className="space-y-0.5">
              <div className="flex items-center gap-2 py-1">
                <div className="w-3.5 h-3.5 rounded bg-muted-foreground/20 animate-pulse" />
                <span className="text-xs font-medium text-muted-foreground/60 animate-pulse">
                  Discovering tools from MCP server…
                </span>
              </div>
              <div className="pl-5 space-y-1.5 pt-0.5">
                {[70, 55, 80, 62].map((w, i) => (
                  <div key={i} className="flex items-center justify-between pr-1">
                    <div className="h-2.5 rounded bg-muted-foreground/15 animate-pulse" style={{ width: `${w}%`, animationDelay: `${i * 120}ms` }} />
                    <div className="w-7 h-4 rounded-full bg-muted-foreground/15 animate-pulse flex-shrink-0" style={{ animationDelay: `${i * 120 + 60}ms` }} />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground/70 italic pl-1">
              {connection.fields.length === 0
                ? 'Click "Configure connection" → Test to discover available tools.'
                : 'Tools are discovered dynamically — expand "Configure connection" and click Test to populate them.'}
            </p>
          )
        )}

        {/* Tools — MCP shows flat "Available tools"; native shows "Read tools" */}
        {readTools.length > 0 && <div className="space-y-0.5">
          <div className="flex items-center gap-2 py-1">
            <BookOpen className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium">Read tools</span>
            <span className="text-xs text-muted-foreground/60">({enabledReadCount}/{readTools.length} active)</span>
          </div>
          <div className="pl-5 space-y-0.5">
            {readTools.map((tool) => {
              const effectiveEnabled = contextEnabled && tool.enabled;
              return (
                <ToolToggleRow
                  key={tool.name}
                  tool={tool}
                  enabled={effectiveEnabled}
                  onToggle={() => onToolToggle(tool.name, tool.enabled, connection)}
                  saving={toolSaving}
                />
              );
            })}
          </div>
        </div>}

        {/* Write tools */}
        {mutationTools.length > 0 && <div className="space-y-0.5">
          <div className="flex items-center gap-2 py-1">
            <Pencil className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium">
              {connection.type?.includes("mcp") ? "Write tools" : "Write-back tools"}
            </span>
            <span className="text-xs text-muted-foreground/60">({enabledMutationCount}/{mutationTools.length} active)</span>
          </div>
          {!mutationWarningDismissed && anyMutationEnabled && (
            <div className="flex items-start gap-2 text-xs px-2.5 py-2 rounded bg-primary/8 border border-primary/20 text-primary mb-1">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span className="flex-1">Allows the agent to create documents and update metadata in DataHub on behalf of users.</span>
              <button onClick={handleDismissWarning} className="flex-shrink-0 hover:opacity-70 transition-opacity">
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
          <div className="pl-5 space-y-0.5">
            {mutationTools.map((tool) => {
              const effectiveEnabled = contextEnabled && enabledMutations.has(tool.name);
              return (
                <ToolToggleRow
                  key={tool.name}
                  tool={tool}
                  enabled={effectiveEnabled}
                  onToggle={() => onMutationToggle(tool.name, enabledMutations.has(tool.name), connection)}
                  saving={toolSaving}
                />
              );
            })}
          </div>
        </div>}

        {/* Configure connection (collapsed by default) */}
        <button
          onClick={() => setConfigExpanded((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {configExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          Configure connection
        </button>

        {configExpanded && (
          <div className="space-y-3 pl-4 border-l border-border/40">
            {connection.fields.map((field) => (
              <FieldRow
                key={field.key}
                field={field}
                value={values[field.key] ?? ""}
                onChange={(v) => setValues((prev) => ({ ...prev, [field.key]: v }))}
              />
            ))}
            {testResult && (
              <div className="rounded border border-border/60 overflow-hidden">
                {testResult.error && !testResult.checks?.length ? (
                  <div className="flex items-start gap-2 text-xs px-3 py-2 bg-red-500/10 text-red-700 dark:text-red-400">
                    <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                    <span>{testResult.error}</span>
                  </div>
                ) : (
                  (testResult.checks ?? []).map((check: DataHubCheckResult, i: number) => (
                    <div
                      key={check.name}
                      className={`flex items-center gap-2.5 px-3 py-2 text-xs ${i > 0 ? "border-t border-border/40" : ""} ${check.success ? "bg-emerald-500/5" : "bg-red-500/5"}`}
                    >
                      {check.success
                        ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                        : <AlertCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />}
                      <span className="font-medium text-foreground w-24 flex-shrink-0">{check.label}</span>
                      <span className={check.success ? "text-muted-foreground" : "text-red-600 dark:text-red-400"}>
                        {check.message}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}
            {saveResult && <p className="text-xs text-muted-foreground px-1">{saveResult}</p>}
            <div className="flex items-center justify-end gap-2">
              <button onClick={handleTest} disabled={testing}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors disabled:opacity-50">
                {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
                Test
              </button>
              <button onClick={handleSave} disabled={saving}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Connection card ---

const TYPE_ICONS: Record<string, React.ReactNode> = {
  datahub: <Link2 className="w-4 h-4" />,
  snowflake: <Database className="w-4 h-4" />,
  chart: <BarChart3 className="w-4 h-4" />,
};

function ConnectionCard({
  connection,
  disabledTools,
  disabledConnections,
  onToolToggle,
  onGlobalToggle,
  toolSaving,
  onOAuthChange,
  onDelete,
}: {
  connection: Connection;
  disabledTools: Set<string>;
  disabledConnections: Set<string>;
  onToolToggle: (name: string, currentlyEnabled: boolean) => void;
  onGlobalToggle: (enable: boolean, connection: Connection) => void;
  toolSaving: boolean;
  onOAuthChange: () => void;
  onDelete?: (name: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(connection.fields.map((f) => [f.key, f.value]))
  );
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message?: string; error?: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState(false);
  const [labelDraft, setLabelDraft] = useState(connection.label);

  const handleLabelSave = async () => {
    setEditingLabel(false);
    if (!labelDraft.trim() || labelDraft === connection.label) return;
    await patchConnectionLabel(connection.name, labelDraft.trim());
    onOAuthChange();
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await testConnection(connection.name));
    } catch (e) {
      setTestResult({ success: false, error: String(e) });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      const body = splitConnectionValues(connection.fields, values);
      const result = await saveConnection(connection.name, body);
      setSaveResult(result.message);
    } catch (e) {
      setSaveResult("Save failed: " + String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={`border rounded-lg overflow-hidden transition-all duration-200 ${
        expanded ? "border-border" : "border-border/60 hover:border-border"
      }`}
    >
      <div className="flex items-center">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 flex items-center gap-3 px-4 py-3 bg-muted/20 hover:bg-muted/40 transition-colors text-left"
        >
          <div
            className={`w-1 h-8 rounded-full flex-shrink-0 ${
              connection.status === "connected"
                ? "bg-emerald-500"
                : connection.status === "error"
                ? "bg-red-500"
                : "bg-amber-400"
            }`}
          />
          <span className="text-muted-foreground flex-shrink-0">
            {TYPE_ICONS[connection.type] ?? <Database className="w-4 h-4" />}
          </span>
          <div className="flex-1 min-w-0" onClick={(e) => e.stopPropagation()}>
            {editingLabel && connection.source === "ui" ? (
              <input
                autoFocus
                value={labelDraft}
                onChange={(e) => setLabelDraft(e.target.value)}
                onBlur={handleLabelSave}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleLabelSave();
                  if (e.key === "Escape") setEditingLabel(false);
                }}
                className="text-sm font-medium bg-background border border-primary/50 rounded px-1.5 py-0.5 w-full outline-none focus:ring-1 focus:ring-primary/50"
              />
            ) : (
              <p
                className={`text-sm font-medium truncate ${connection.source === "ui" ? "cursor-text hover:text-primary transition-colors" : ""}`}
                title={connection.source === "ui" ? "Click to rename" : undefined}
                onClick={() => {
                  if (connection.source === "ui") {
                    setLabelDraft(connection.label);
                    setEditingLabel(true);
                  }
                }}
              >
                {connection.label}
              </p>
            )}
            <p className="text-xs text-muted-foreground capitalize">{connection.type}</p>
            <DataHubCoverageBadge engineName={connection.name} />
          </div>
          <StatusBadge status={connection.status} />
          <span className="text-muted-foreground/50 ml-1">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </span>
        </button>
        {/* Enable / disable toggle */}
        <button
          onClick={(e) => { e.stopPropagation(); onGlobalToggle(disabledConnections.has(connection.name), connection); }}
          disabled={toolSaving}
          title={disabledConnections.has(connection.name) ? "Enable data source" : "Disable data source"}
          className={`mx-1 relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
            !disabledConnections.has(connection.name) ? "bg-primary" : "bg-muted-foreground/30"
          }`}
          role="switch"
          aria-checked={!disabledConnections.has(connection.name)}
        >
          <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200 mt-0.5 ${
            !disabledConnections.has(connection.name) ? "translate-x-4" : "translate-x-0.5"
          }`} />
        </button>
        {/* Source indicator / delete */}
        {(connection.source ?? "yaml") === "yaml" ? (
          <span className="px-3 text-muted-foreground/30" title="Defined in config.yaml">
            <Lock className="w-3 h-3" />
          </span>
        ) : (
          <button
            onClick={() => onDelete?.(connection.name)}
            className="px-3 text-muted-foreground/40 hover:text-red-500 transition-colors"
            title="Delete connection"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {expanded && (
        <div className="px-4 py-4 border-t border-border/60 space-y-3 bg-background">
          {/* Connection fields */}
          {connection.fields.length > 0 && (
            <div className="space-y-2.5">
              {connection.fields.map((field) => (
                <FieldRow
                  key={field.key}
                  field={field}
                  value={values[field.key] ?? ""}
                  onChange={(v) => setValues((prev) => ({ ...prev, [field.key]: v }))}
                />
              ))}
            </div>
          )}

          {testResult && (
            <div
              className={`flex items-start gap-2 text-xs px-3 py-2 rounded border ${
                testResult.success
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : "bg-red-50 border-red-200 text-red-700"
              }`}
            >
              {testResult.success ? (
                <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              ) : (
                <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              )}
              <span>{testResult.success ? testResult.message : testResult.error}</span>
            </div>
          )}

          {saveResult && <p className="text-xs text-muted-foreground px-1">{saveResult}</p>}

          {connection.fields.length > 0 && (
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={handleTest}
                disabled={testing}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border
                           hover:bg-muted/50 transition-colors disabled:opacity-50"
              >
                {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />}
                Test
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded
                           bg-primary text-primary-foreground hover:bg-primary/90
                           transition-colors disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save
              </button>
            </div>
          )}

          {/* Tool toggles */}
          {(connection.tools ?? []).length > 0 && (
            <div className={`${connection.fields.length > 0 ? "border-t border-border/40 pt-3" : ""}`}>
              <div className="flex items-center gap-1.5 mb-2">
                <Wrench className="w-3 h-3 text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Available Tools</p>
              </div>
              <div className="space-y-0.5">
                {(connection.tools ?? []).map((tool) => (
                  <ToolToggleRow
                    key={tool.name}
                    tool={tool}
                    enabled={!disabledTools.has(tool.name)}
                    onToggle={() => onToolToggle(tool.name, !disabledTools.has(tool.name))}
                    saving={toolSaving}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Auth section — replaces ad-hoc SSO panel for engine connections */}
          {OAUTH_SUPPORTED.has(connection.type) && (
            <div className="border-t border-border/40 pt-3 mt-1">
              <SnowflakeAuthSection
                connectedAuth={
                  connection.oauth?.connected
                    ? { method: "sso" as const, username: connection.oauth.username }
                    : connection.auth_method
                    ? {
                        method: connection.auth_method as "password" | "privatekey" | "sso" | "pat" | "oauth",
                        username: connection.fields.find((f) => f.key === "user")?.value ?? "",
                      }
                    : null
                }
                onConnect={async (method, fields) => {
                  if (method === "sso") {
                    await browserSso(connection.name, undefined, fields.username);
                  } else if (method === "password") {
                    await saveConnection(connection.name, {
                      config: { user: fields.username },
                      secrets: { password: fields.password },
                    });
                  } else if (method === "privatekey") {
                    await saveConnection(connection.name, {
                      config: { user: fields.username },
                      secrets: { private_key: fields.private_key },
                    });
                  } else if (method === "oauth") {
                    await saveOAuthAppConfig(connection.name, {
                      client_id: fields.client_id,
                      client_secret: fields.client_secret,
                      redirect_uri: fields.redirect_uri,
                    });
                    initiateOAuthFlow(
                      connection.name,
                      () => {},
                      (err) => { throw new Error(err); },
                    );
                  } else if (method === "pat") {
                    // PAT: store via the SSO credential endpoint with auth_type=pat
                    await saveSnowflakePat(connection.name, fields.token, fields.username);
                  }
                  onOAuthChange();
                }}
                onDisconnect={async () => {
                  await disconnectOAuth(connection.name);
                  onOAuthChange();
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- Connections section ---

function ConnectionsSection() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState<Set<string>>(new Set());

  const {
    disabledTools: disabledToolsArr,
    enabledMutations: enabledMutationsArr,
    disabledConnections: disabledConnectionsArr,
    saving: toolSaving,
    isToolDisabled,
    isMutationEnabled,
    isConnectionDisabled,
    initialize,
    toggleTool,
    toggleMutation,
    toggleConnection,
  } = useConnectionSettingsStore();

  // Expose as Sets for the card components that still consume them that way
  const disabledTools = new Set(disabledToolsArr);
  const enabledMutations = new Set(enabledMutationsArr);
  const disabledConnections = new Set(disabledConnectionsArr);

  useEffect(() => {
    listConnections()
      .then((conns) => {
        setConnections(conns);
        initialize(conns);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [initialize]);

  const refreshConnections = useCallback(() => {
    listConnections().then((conns) => { setConnections(conns); initialize(conns); }).catch(() => {});
  }, [initialize]);

  const handleToolToggle = useCallback(
    async (toolName: string, currentlyEnabled: boolean, connection?: Connection) => {
      const CONTEXT_PLATFORM_TYPES = new Set(["datahub", "datahub-mcp"]);
      if (connection && CONTEXT_PLATFORM_TYPES.has(connection.type)) {
        // Per-connection: update _disabled_tools in the platform's DB config
        const currentDisabled = (connection.tools ?? [])
          .filter(t => !t.enabled)
          .map(t => t.name);
        const newDisabled = currentlyEnabled
          ? [...currentDisabled, toolName]
          : currentDisabled.filter(n => n !== toolName);
        await updateConnectionTools(connection.name, newDisabled);
        refreshConnections();
      } else {
        // Engine connections: use global store
        await toggleTool(toolName, currentlyEnabled);
      }
    },
    [toggleTool, refreshConnections]
  );

  const handleMutationToggle = useCallback(
    async (toolName: string, currentlyEnabled: boolean, _connection?: Connection) => {
      // Write-back tools are always global (enabled_mutations setting) —
      // they control what the agent is ALLOWED to do, not which connection to use.
      await toggleMutation(toolName, currentlyEnabled);
    },
    [toggleMutation]
  );

  const handleGlobalContextToggle = useCallback(
    (enable: boolean, connection: Connection) => toggleConnection(connection.name, enable),
    [toggleConnection]
  );

  const { setEngines } = useConversationsStore();

  const handleConnectionDone = useCallback(
    async (payload: NewConnectionPayload, plugin: ConnectionPlugin) => {
      await createConnection({
        name: payload.name,
        type: plugin.id,
        label: payload.label,
        config: payload.config,
        category: plugin.category,
        mcp_config: payload.mcpConfig,
      });
      if (plugin.category === "engine") {
        listEngines().then(setEngines).catch(() => {});
      }
      await payload.postCreate?.(payload.name);
      refreshConnections();

      // MCP: show discovering state and poll until tools land (max 20s)
      if (payload.mcpConfig) {
        const connName = payload.name.trim().toLowerCase().replace(/ /g, "-");
        setDiscovering((prev) => new Set(prev).add(connName));
        const start = Date.now();
        const poll = setInterval(async () => {
          try {
            const conns = await listConnections();
            setConnections(conns);
            const target = conns.find((c) => c.name === connName);
            if ((target?.tools ?? []).length > 0 || Date.now() - start > 20_000) {
              clearInterval(poll);
              setDiscovering((prev) => { const s = new Set(prev); s.delete(connName); return s; });
            }
          } catch { clearInterval(poll); }
        }, 1500);
      }
    },
    [setEngines, refreshConnections]
  );

  const handleDelete = async (name: string) => {
    try { await deleteConnection(name); refreshConnections(); }
    catch (e) { setError(String(e)); }
  };

  if (loading)
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );

  if (error)
    return (
      <div className="flex items-center gap-2 text-sm text-red-500 py-8">
        <AlertCircle className="w-4 h-4" />
        {error}
      </div>
    );

  const CONTEXT_PLATFORM_TYPES = new Set(["datahub", "datahub-mcp"]);
  const datahubConns = connections.filter((c) => CONTEXT_PLATFORM_TYPES.has(c.type));
  const engineConns = connections.filter((c) => !CONTEXT_PLATFORM_TYPES.has(c.type) && c.type !== "chart");

  return (
    <div className="space-y-6">
      {/* Context Platform section */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 mb-1">
          <Layers className="w-3.5 h-3.5 text-muted-foreground" />
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Context Platform</p>
        </div>
        {datahubConns.map((conn) => (
          <DataHubCard
            key={conn.name}
            connection={conn}
            disabledTools={disabledTools}
            enabledMutations={enabledMutations}
            disabledConnections={disabledConnections}
            onToolToggle={handleToolToggle}
            onMutationToggle={handleMutationToggle}
            onGlobalToggle={handleGlobalContextToggle}
            toolSaving={toolSaving}
            onOAuthChange={refreshConnections}
            onDelete={handleDelete}
            discovering={discovering.has(conn.name)}
          />
        ))}
        {datahubConns.length === 0 && (
          <p className="text-xs text-muted-foreground/60 italic px-1">
            No context platform configured. Add one below or set DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN in config.yaml.
          </p>
        )}
        <AddConnectionFlow
          category="context_platform"
          onDone={handleConnectionDone}
          buttonLabel="Add context platform"
        />
      </div>

      {/* Data Sources section */}
      <div className="space-y-2">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Database className="w-3.5 h-3.5 text-muted-foreground" />
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Data Sources</p>
          </div>
        </div>
        {engineConns.map((conn) => (
          <ConnectionCard
            key={conn.name}
            connection={conn}
            disabledTools={disabledTools}
            disabledConnections={disabledConnections}
            onToolToggle={handleToolToggle}
            onGlobalToggle={handleGlobalContextToggle}
            toolSaving={toolSaving}
            onOAuthChange={refreshConnections}
            onDelete={handleDelete}
          />
        ))}
        <AddConnectionFlow
          category="engine"
          onDone={handleConnectionDone}
          buttonLabel="Add data source"
        />
      </div>
    </div>
  );
}

// --- Prompt section ---

function PromptSection() {
  const [content, setContent] = useState("");
  const [isCustom, setIsCustom] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    getPrompt()
      .then((d) => {
        setContent(d.content);
        setIsCustom(d.is_custom);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setStatus(null);
    try {
      await savePrompt(content);
      setIsCustom(true);
      setStatus("Prompt saved.");
    } catch {
      setStatus("Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setStatus(null);
    try {
      await resetPrompt();
      const d = await getPrompt();
      setContent(d.content);
      setIsCustom(false);
      setStatus("Reset to default.");
    } catch {
      setStatus("Reset failed.");
    } finally {
      setResetting(false);
    }
  };

  if (loading)
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Customize the system prompt sent to the AI on every conversation.
          </p>
          <p className="text-xs text-muted-foreground/70 mt-1">
            Use <code className="bg-muted px-1 py-0.5 rounded text-xs font-mono">{"{engine_name}"}</code> as a
            placeholder for the selected query engine.
          </p>
        </div>
        {isCustom && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 flex-shrink-0 ml-3">
            Customized
          </span>
        )}
      </div>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={20}
        className="w-full text-xs font-mono bg-muted/30 border border-border rounded-lg px-3 py-3
                   focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y leading-relaxed"
        spellCheck={false}
      />

      {status && <p className="text-xs text-muted-foreground">{status}</p>}

      <div className="flex items-center gap-2 justify-end">
        {isCustom && (
          <button
            onClick={handleReset}
            disabled={resetting}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border
                       hover:bg-muted/50 transition-colors disabled:opacity-50"
          >
            {resetting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />}
            Reset to Default
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded
                     bg-primary text-primary-foreground hover:bg-primary/90
                     transition-colors disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Save Prompt
        </button>
      </div>
    </div>
  );
}

// --- Display section ---

function DisplaySection() {
  const { appName: storeAppName, logoUrl: storeLogoUrl, setDisplay } = useDisplayStore();
  const [appName, setAppName] = useState(storeAppName);
  const [logoUrl, setLogoUrl] = useState(storeLogoUrl);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    getDisplaySettings()
      .then((d) => {
        setAppName(d.app_name);
        setLogoUrl(d.logo_url);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setStatus(null);
    setDisplay(appName, logoUrl);
    try {
      await saveDisplaySettings({ app_name: appName, logo_url: logoUrl });
      setStatus("Display settings saved.");
    } catch {
      setStatus("Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading)
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin" />
      </div>
    );

  return (
    <div className="space-y-6 max-w-sm">
      <p className="text-sm text-muted-foreground">
        Customize how the app appears to users.
      </p>

      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-foreground">App Name</label>
          <input
            type="text"
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
            placeholder="Analytics Agent"
            className="w-full text-sm bg-background border border-border rounded px-3 py-2
                       focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-foreground">Logo URL</label>
          <input
            type="url"
            value={logoUrl}
            onChange={(e) => setLogoUrl(e.target.value)}
            placeholder="https://example.com/logo.png"
            className="w-full text-sm bg-background border border-border rounded px-3 py-2
                       focus:outline-none focus:ring-1 focus:ring-primary/50 font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground/70">
            Leave blank to use the default logo. PNG, SVG, or any image URL.
          </p>
        </div>

        {/* Preview */}
        {(appName || logoUrl) && (
          <div className="border border-border rounded-lg p-3 bg-muted/20">
            <p className="text-xs text-muted-foreground mb-2">Preview</p>
            <div className="flex items-center gap-2">
              {logoUrl ? (
                <img
                  src={logoUrl}
                  alt="Logo preview"
                  className="w-6 h-6 object-contain"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
                />
              ) : (
                <svg width="22" height="22" viewBox="0 0 64 64" fill="none" aria-hidden>
                  <path d="M8 42 A30 30 0 0 1 52 10" stroke="#0078D4" strokeWidth="7" strokeLinecap="round"/>
                  <path d="M56 42 A30 30 0 0 0 12 10" stroke="#E8A030" strokeWidth="7" strokeLinecap="round"/>
                  <circle cx="24" cy="28" r="3.5" fill="#D44B20"/>
                  <circle cx="32" cy="28" r="3.5" fill="#D44B20"/>
                  <circle cx="40" cy="28" r="3.5" fill="#D44B20"/>
                  <path d="M8 42 L3 54 L17 45" stroke="#0078D4" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
                  <path d="M56 42 L61 54 L47 45" stroke="#E8A030" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              )}
              <span className="text-base font-semibold tracking-tight" style={{ letterSpacing: "-0.02em" }}>
                {appName || "Analytics Agent"}
              </span>
            </div>
          </div>
        )}
      </div>

      {status && <p className="text-xs text-muted-foreground">{status}</p>}

      <button
        onClick={handleSave}
        disabled={saving}
        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded
                   bg-primary text-primary-foreground hover:bg-primary/90
                   transition-colors disabled:opacity-50"
      >
        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
        Save Display Settings
      </button>
    </div>
  );
}

// --- Nav item ---

function NavItem({
  label,
  icon,
  active,
  onClick,
  badge,
}: {
  label: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  badge?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-left text-sm transition-colors ${
        active
          ? "bg-primary/10 text-primary font-medium"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
      }`}
    >
      <span className="flex-shrink-0 relative">
        {icon}
        {badge && (
          <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
          </span>
        )}
      </span>
      {label}
    </button>
  );
}

// --- Section headers ---

const SECTION_LABELS: Record<Section, string> = {
  connections: "Connections",
  model: "Model",
  prompt: "Prompt",
  display: "Display Settings",
  about: "About",
};

const SECTION_DESCRIPTIONS: Record<Section, string> = {
  connections: "Manage your context platform (DataHub) and data source connections. Toggle tools and enable write-back.",
  model: "Choose your AI provider, model, and API key.",
  prompt: "View and customize the system prompt used by the AI assistant.",
  display: "Customize the app name and logo.",
  about: "Current version, release notes, and update status.",
};

// --- Main modal ---

export function SettingsModal({ onClose, updateAvailable }: Props) {
  const [section, setSection] = useState<Section>("connections");

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <Settings2 className="w-4 h-4 text-muted-foreground" />
          <h1 className="text-sm font-semibold">Settings</h1>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-md text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left nav */}
        <nav className="w-52 flex-shrink-0 border-r border-border flex flex-col">
          <div className="p-3 space-y-0.5 flex-1">
            <NavItem
              label="Connections"
              icon={<Link2 className="w-4 h-4" />}
              active={section === "connections"}
              onClick={() => setSection("connections")}
            />
            <NavItem
              label="Model"
              icon={<Cpu className="w-4 h-4" />}
              active={section === "model"}
              onClick={() => setSection("model")}
            />
            <NavItem
              label="Prompt"
              icon={<FileText className="w-4 h-4" />}
              active={section === "prompt"}
              onClick={() => setSection("prompt")}
            />
            <NavItem
              label="Display Settings"
              icon={<Monitor className="w-4 h-4" />}
              active={section === "display"}
              onClick={() => setSection("display")}
            />
            <NavItem
              label="About"
              icon={<Info className="w-4 h-4" />}
              active={section === "about"}
              onClick={() => setSection("about")}
              badge={updateAvailable}
            />
          </div>
          <div className="px-3 py-3 border-t border-border flex items-center justify-between">
            <DataHubBadge />
            <ThemeSwitcher />
          </div>
        </nav>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 max-w-3xl w-full mx-auto">
          {/* Section header */}
          <div className="mb-6">
            <h2 className="text-base font-semibold">{SECTION_LABELS[section]}</h2>
            <p className="text-xs text-muted-foreground mt-1">{SECTION_DESCRIPTIONS[section]}</p>
          </div>

          {/* Keep ModelSection always mounted so its state survives tab switches */}
          <div className={section !== "connections" ? "hidden" : ""}><ConnectionsSection /></div>
          <div className={section !== "model"       ? "hidden" : ""}><ModelSection /></div>
          <div className={section !== "prompt"      ? "hidden" : ""}><PromptSection /></div>
          <div className={section !== "display"     ? "hidden" : ""}><DisplaySection /></div>
          {section === "about" && <AboutSection />}
        </div>
      </div>
    </div>
  );
}
