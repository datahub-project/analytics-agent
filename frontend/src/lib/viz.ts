export interface VizIntent {
  version: 1;
  kind: "kpi" | "bar" | "diverging_bar" | "line" | "area";
  title: string;
  value: string;
  category?: string | null;
  series?: string | null;
  value_label?: string | null;
  category_label?: string | null;
  format?: "number" | "percent" | "currency";
  currency?: "USD" | "EUR" | "GBP" | "JPY" | "INR";
}
export type Row = Record<string, unknown>;

/** Validate persisted/network input before it reaches SVG geometry. */
export function isRenderableIntent(
  intent: unknown,
  rows: unknown,
): intent is VizIntent {
  if (
    !intent ||
    typeof intent !== "object" ||
    !Array.isArray(rows) ||
    !rows.length ||
    rows.length > 5000
  )
    return false;
  const v = intent as VizIntent;
  if (
    v.version !== 1 ||
    !["kpi", "bar", "diverging_bar", "line", "area"].includes(v.kind) ||
    typeof v.title !== "string" ||
    !v.title ||
    typeof v.value !== "string" ||
    !v.value
  )
    return false;
  if (v.format != null && !["number", "percent", "currency"].includes(v.format))
    return false;
  if (
    v.currency != null &&
    !["USD", "EUR", "GBP", "JPY", "INR"].includes(v.currency)
  )
    return false;
  if (
    [v.value_label, v.category_label].some(
      (x) => x != null && typeof x !== "string",
    )
  )
    return false;
  if (
    [v.category, v.series].some(
      (x) => x != null && (typeof x !== "string" || !x),
    )
  )
    return false;
  if ((v.kind !== "kpi" || rows.length > 1) && !v.category) return false;
  if (v.series && !["line", "area"].includes(v.kind)) return false;
  const roles = [v.value, v.category, v.series].filter(Boolean);
  if (new Set(roles).size !== roles.length) return false;
  if (["bar", "diverging_bar"].includes(v.kind) && rows.length > 50)
    return false;
  const seen = new Set<string>(),
    series = new Set<string>();
  let numeric = false;
  for (const row of rows) {
    if (
      !row ||
      typeof row !== "object" ||
      Array.isArray(row) ||
      !(v.value in row)
    )
      return false;
    const value = row[v.value];
    if (
      value !== null &&
      (typeof value !== "number" || !Number.isFinite(value))
    )
      return false;
    if (typeof value === "number") numeric = true;
    const key: string[] = [];
    for (const col of [v.category, v.series]) {
      if (!col) continue;
      const label = row[col];
      if (
        typeof label !== "string" &&
        !(typeof label === "number" && Number.isFinite(label))
      )
        return false;
      key.push(String(label));
    }
    if (v.category) {
      const id = JSON.stringify(key);
      if (seen.has(id)) return false;
      seen.add(id);
    }
    if (v.series) series.add(String(row[v.series]));
  }
  return numeric && series.size <= 8;
}
export function formatValue(
  value: unknown,
  intent: VizIntent,
  compact = false,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "No value";
  return new Intl.NumberFormat("en-US", {
    style:
      intent.format === "currency"
        ? "currency"
        : intent.format === "percent"
          ? "percent"
          : "decimal",
    currency: intent.currency || "USD",
    maximumFractionDigits: 2,
    ...(compact ? { notation: "compact" as const } : {}),
  }).format(value);
}

export function numericDomain(values: number[]): [number, number] {
  const low = Math.min(0, ...values),
    high = Math.max(0, ...values);
  return low === high ? [0, 1] : [low, high];
}
