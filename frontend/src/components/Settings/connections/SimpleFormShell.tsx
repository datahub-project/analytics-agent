import { useState } from "react";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";
import type { FieldDef, NewConnectionPayload } from "./types";
import { ArrayField } from "./fields/ArrayField";
import { KeyValueField } from "./fields/KeyValueField";

// ── JSON field ────────────────────────────────────────────────────────────

function JsonField({
  def,
  value,
  onChange,
}: {
  def: FieldDef;
  value: string;
  onChange: (v: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  const validate = (v: string) => {
    if (!v.trim()) { setError(null); return; }
    try { JSON.parse(v); setError(null); }
    catch { setError("Invalid JSON"); }
  };

  const handleBlur = () => {
    if (!value.trim()) return;
    try {
      // Pretty-print on blur so it's readable
      onChange(JSON.stringify(JSON.parse(value), null, 2));
      setError(null);
    } catch {
      setError("Invalid JSON");
    }
  };

  const isValid = value.trim() && !error;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">
          {def.label}
          {def.required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
        {value.trim() && (
          isValid
            ? <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
            : <AlertCircle className="w-3.5 h-3.5 text-red-400" />
        )}
      </div>
      <textarea
        value={value}
        placeholder={def.placeholder}
        rows={4}
        onChange={(e) => { onChange(e.target.value); validate(e.target.value); }}
        onBlur={handleBlur}
        className={[
          "w-full text-xs font-mono bg-background border rounded px-2.5 py-1.5 resize-y",
          "focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/40",
          "leading-relaxed",
          error ? "border-red-400" : "border-border",
        ].join(" ")}
      />
      {error && <p className="text-xs text-red-400 flex items-center gap-1"><AlertCircle className="w-3 h-3" />{error}</p>}
      {def.hint && <p className="text-xs text-muted-foreground/60">{def.hint}</p>}
    </div>
  );
}

// ── Primitive: single field ───────────────────────────────────────────────

function FormField({
  def,
  value,
  onChange,
}: {
  def: FieldDef;
  value: string;
  onChange: (v: string) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const baseClass =
    "w-full text-xs bg-background border border-border rounded px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground/40";
  const monoClass = baseClass + " font-mono";

  if (def.type === "array") {
    const arr = value ? value.split("\n").filter(Boolean) : [];
    return (
      <ArrayField
        label={def.label}
        values={arr}
        onChange={(v) => onChange(v.join("\n"))}
        placeholder={def.placeholder}
        hint={def.hint}
      />
    );
  }

  if (def.type === "keyvalue") {
    const pairs = value
      ? value.split("\n").map((line) => {
          const eq = line.indexOf("=");
          return eq >= 0
            ? { key: line.slice(0, eq), value: line.slice(eq + 1) }
            : { key: line, value: "" };
        })
      : [];
    return (
      <KeyValueField
        label={def.label}
        pairs={pairs}
        onChange={(p) => onChange(p.map((x) => `${x.key}=${x.value}`).join("\n"))}
        hint={def.hint}
      />
    );
  }

  if (def.type === "json") {
    return <JsonField def={def} value={value} onChange={onChange} />;
  }

  if (def.type === "password") {
    return (
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          {def.label}
          {def.required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
        <div className="relative">
          <input
            type={revealed ? "text" : "password"}
            value={value}
            placeholder={def.placeholder}
            onChange={(e) => onChange(e.target.value)}
            className={monoClass + " pr-8"}
          />
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground"
          >
            {revealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
        {def.hint && <p className="text-xs text-muted-foreground/60">{def.hint}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">
        {def.label}
        {def.required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      <input
        type="text"
        value={value}
        placeholder={def.placeholder}
        onChange={(e) => onChange(e.target.value)}
        onBlur={(e) => { if (def.transform) onChange(def.transform(e.target.value)); }}
        className={def.type === "mono" ? monoClass : baseClass}
      />
      {def.hint && <p className="text-xs text-muted-foreground/60">{def.hint}</p>}
    </div>
  );
}

// ── Shell ─────────────────────────────────────────────────────────────────

export function SimpleFormShell({
  fields,
  onDone,
  onCancel,
  extraActions,
}: {
  fields: FieldDef[];
  onDone: (payload: NewConnectionPayload) => void;
  onCancel: () => void;
  /** Slot for extra buttons next to Save (e.g. "Save & Sign in with SSO"). */
  extraActions?: (values: Record<string, string>, name: string) => React.ReactNode;
}) {
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(fields.map((f) => [f.key, ""]))
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: string, v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const missing = fields.filter((f) => f.required && !values[f.key]?.trim());
  const canSave = name.trim().length > 0 && missing.length === 0;

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      await onDone({ name: name.trim(), label: label.trim() || undefined, config: values });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Name + label */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-connection"
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

      {/* Plugin-defined fields */}
      {fields.map((f) => (
        <FormField key={f.key} def={f} value={values[f.key] ?? ""} onChange={(v) => set(f.key, v)} />
      ))}

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-2 justify-end flex-wrap pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs px-3 py-1.5 rounded border border-border hover:bg-muted/50 transition-colors"
        >
          Cancel
        </button>
        {extraActions?.(values, name.trim())}
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
