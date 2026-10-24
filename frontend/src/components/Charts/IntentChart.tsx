import { useEffect, useId, useRef, useState } from "react";
import { scaleLinear, scaleBand, scalePoint } from "@visx/scale";
import { AreaClosed, LinePath } from "@visx/shape";
import { Download, Table2, ChartNoAxesCombined } from "lucide-react";
import type { ChartPayload } from "@/types";
import {
  formatValue,
  isRenderableIntent,
  numericDomain,
  type Row,
  type VizIntent,
} from "@/lib/viz";
import { chartColors, chartNegative } from "./tokens";
import { downloadChartPng } from "./export";
import "./charts.css";

const text = (value: unknown) =>
  value == null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const shorten = (value: string, length: number) =>
  value.length > length ? value.slice(0, length - 1) + "…" : value;

export function IntentChart({ payload }: { payload: ChartPayload }) {
  const ref = useRef<HTMLElement>(null),
    svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(640),
    [table, setTable] = useState(false);
  const [exporting, setExporting] = useState(false),
    [error, setError] = useState("");
  const id = useId();
  const rows = Array.isArray(payload.rows)
    ? payload.rows.filter(
        (r) => r && typeof r === "object" && !Array.isArray(r),
      )
    : [];
  const valid = isRenderableIntent(payload.viz_intent, payload.rows);
  const intent = valid ? payload.viz_intent! : undefined;
  const columns = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(240, entry.contentRect.width)),
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const download = async () => {
    if (!svg.current || !intent) return;
    setExporting(true);
    setError("");
    try {
      await downloadChartPng(svg.current, intent.title);
    } catch {
      setError("Could not export the chart. Please try again.");
    } finally {
      setExporting(false);
    }
  };
  return (
    <section className="intent-chart" ref={ref} aria-labelledby={id}>
      <header className="chart-header">
        <div>
          <h3 id={id}>{intent?.title || "Query results"}</h3>
          <p>
            {rows.length.toLocaleString()} {rows.length === 1 ? "row" : "rows"}
            {intent?.value_label ? ` · ${intent.value_label}` : ""}
          </p>
        </div>
        {valid && (
          <div className="chart-actions print:hidden">
            <button aria-pressed={!table} onClick={() => setTable(false)}>
              <ChartNoAxesCombined size={14} />
              Chart
            </button>
            <button aria-pressed={table} onClick={() => setTable(true)}>
              <Table2 size={14} />
              Data
            </button>
            <button
              onClick={download}
              disabled={exporting}
              aria-label="Download chart as PNG"
            >
              <Download size={14} />
              {exporting ? "Saving…" : "PNG"}
            </button>
          </div>
        )}
      </header>
      {!valid && (
        <p role="status">
          {payload.viz_error ||
            "This chart format is unavailable. The result data is shown below."}
        </p>
      )}
      {intent && (
        <div
          className={
            table ? "chart-graphic chart-graphic-hidden" : "chart-graphic"
          }
        >
          <svg
            ref={svg}
            viewBox={`0 38 ${width} ${chartHeight(intent, rows) - 38}`}
            role="img"
            aria-label={intent.title}
          >
            <title>{intent.title}</title>
            <desc>
              {payload.reasoning ||
                `${intent.kind} chart of ${intent.value}. Exact values are available in the Data view.`}
            </desc>
            <text x={0} y={18} className="chart-export-title">
              {shorten(intent.title, Math.floor(width / 8))}
            </text>
            <g transform="translate(0, 38)">
              <Marks intent={intent} rows={rows} width={width} />
            </g>
          </svg>
        </div>
      )}
      {(table || !valid) && (
        <div
          className="chart-table"
          tabIndex={0}
          role="region"
          aria-label="Chart data"
        >
          <table>
            <caption className="sr-only">
              {intent?.title || "Query results"} — underlying data
            </caption>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th scope="col" key={c}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c}>{text(r[c])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p>No result rows available.</p>}
        </div>
      )}
      {payload.truncated && (
        <p className="chart-reasoning">
          This chart shows a limited result set. Refine the query to include all
          relevant data.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {payload.reasoning && (
        <p className="chart-reasoning">{payload.reasoning}</p>
      )}
    </section>
  );
}
function chartHeight(v: VizIntent, rows: Row[]) {
  return v.kind === "kpi"
    ? 215
    : ["bar", "diverging_bar"].includes(v.kind)
      ? Math.max(210, rows.length * 34 + 110)
      : 350;
}
function Marks({
  intent: v,
  rows,
  width,
}: {
  intent: VizIntent;
  rows: Row[];
  width: number;
}) {
  if (v.kind === "kpi") return <Kpi intent={v} rows={rows} width={width} />;
  if (v.kind === "bar" || v.kind === "diverging_bar")
    return <Bars intent={v} rows={rows} width={width} />;
  return <Trend intent={v} rows={rows} width={width} />;
}
function Kpi({
  intent: v,
  rows,
  width,
}: {
  intent: VizIntent;
  rows: Row[];
  width: number;
}) {
  const latest = rows[rows.length - 1];
  const x = scaleLinear({
    domain: [0, Math.max(1, rows.length - 1)],
    range: [2, width - 2],
  });
  const y = scaleLinear({
    domain: numericDomain(
      rows
        .map((r) => r[v.value])
        .filter((n): n is number => typeof n === "number"),
    ),
    range: [155, 103],
  });
  return (
    <>
      <text
        x={0}
        y={48}
        className="chart-kpi"
        style={{
          fontSize: Math.min(
            44,
            (width / Math.max(8, formatValue(latest[v.value], v).length)) * 1.6,
          ),
        }}
      >
        {formatValue(latest[v.value], v)}
      </text>
      <text x={0} y={75} className="chart-secondary">
        {v.category
          ? `Latest · ${text(latest[v.category])}`
          : v.value_label || v.value}
      </text>
      {rows.length > 1 && (
        <LinePath<Row>
          data={rows}
          defined={(r) => typeof r[v.value] === "number"}
          x={(_, i) => x(i)}
          y={(r) => y(r[v.value] as number)}
          stroke={chartColors[0]}
          strokeWidth={2.5}
        />
      )}
    </>
  );
}
function Bars({
  intent: v,
  rows,
  width,
}: {
  intent: VizIntent;
  rows: Row[];
  width: number;
}) {
  const left = Math.min(155, width * 0.32),
    right = width > 450 ? 78 : 58;
  const h = Math.max(100, rows.length * 34);
  const x = scaleLinear({
    domain: numericDomain(
      rows
        .map((r) => r[v.value])
        .filter((n): n is number => typeof n === "number"),
    ),
    range: [left, width - right],
    nice: true,
  });
  const y = scaleBand({
    domain: rows.map((_, i) => String(i)),
    range: [0, h],
    padding: 0.3,
  });
  return (
    <>
      {x.ticks(4).map((t) => (
        <g key={t}>
          <line
            x1={x(t)}
            x2={x(t)}
            y1={0}
            y2={h}
            className={t === 0 ? "chart-zero" : "chart-grid"}
          />
          <text
            x={x(t)}
            y={h + 23}
            textAnchor="middle"
            className="chart-secondary"
          >
            {formatValue(t, v, true)}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const value = r[v.value],
          label = text(r[v.category!]),
          yy = y(String(i))!;
        const n = typeof value === "number" ? value : 0;
        return (
          <g
            key={i}
            tabIndex={0}
            aria-label={`${label}: ${formatValue(value, v)}`}
          >
            <title>
              {label}: {formatValue(value, v)}
            </title>
            <text
              x={left - 12}
              y={yy + y.bandwidth() / 2}
              dominantBaseline="middle"
              textAnchor="end"
              className="chart-label"
            >
              {shorten(label, Math.floor((left - 15) / 7))}
            </text>
            {typeof value === "number" && (
              <rect
                x={Math.min(x(0), x(n))}
                y={yy}
                width={Math.max(n === 0 ? 1 : 0, Math.abs(x(n) - x(0)))}
                height={y.bandwidth()}
                rx={3}
                fill={n < 0 ? chartNegative : chartColors[0]}
              />
            )}
            <text
              x={width - 2}
              y={yy + y.bandwidth() / 2}
              dominantBaseline="middle"
              textAnchor="end"
              className="chart-label"
            >
              {formatValue(value, v, true)}
            </text>
          </g>
        );
      })}
      <text
        x={(left + width - right) / 2}
        y={h + 49}
        textAnchor="middle"
        className="chart-secondary"
      >
        {v.value_label || v.value}
      </text>
    </>
  );
}
function Trend({
  intent: v,
  rows,
  width,
}: {
  intent: VizIntent;
  rows: Row[];
  width: number;
}) {
  const categories = [...new Set(rows.map((r) => String(r[v.category!])))];
  const series = v.series
    ? [...new Set(rows.map((r) => String(r[v.series!])))]
    : [v.value_label || v.value];
  const x = scalePoint({
    domain: categories,
    range: [68, width - 14],
    padding: 0.15,
  });
  const y = scaleLinear({
    domain: numericDomain(
      rows
        .map((r) => r[v.value])
        .filter((n): n is number => typeof n === "number"),
    ),
    range: [210, 25],
    nice: true,
  });
  const step = Math.max(
    1,
    Math.ceil(categories.length / Math.max(2, Math.floor(width / 95))),
  );
  return (
    <>
      <text x={0} y={10} className="chart-secondary">
        {v.value_label || v.value}
      </text>
      {y.ticks(4).map((t) => (
        <g key={t}>
          <line
            x1={68}
            x2={width - 14}
            y1={y(t)}
            y2={y(t)}
            className={t === 0 ? "chart-zero" : "chart-grid"}
          />
          <text
            x={58}
            y={y(t)}
            dominantBaseline="middle"
            textAnchor="end"
            className="chart-secondary"
          >
            {formatValue(t, v, true)}
          </text>
        </g>
      ))}
      {categories
        .filter((_, i) => i % step === 0)
        .map((c) => (
          <text
            key={c}
            x={x(c)}
            y={232}
            textAnchor="middle"
            className="chart-secondary"
          >
            {shorten(c, 12)}
          </text>
        ))}
      {series.map((name, index) => {
        const byCategory = new Map(
          rows
            .filter((r) => !v.series || String(r[v.series]) === name)
            .map((r) => [String(r[v.category!]), r]),
        );
        // Explicitly fill missing categories with null to avoid bridging missing observations.
        const points = categories.map(
          (c) => byCategory.get(c) || { [v.category!]: c, [v.value]: null },
        );
        const color = chartColors[index];
        const props = {
          data: points,
          defined: (r: Row) => typeof r[v.value] === "number",
          x: (r: Row) => x(String(r[v.category!]))!,
          y: (r: Row) => y(r[v.value] as number),
        };
        return (
          <g key={name}>
            {v.kind === "area" && (
              <AreaClosed<Row>
                {...props}
                yScale={y}
                y0={y(0)}
                fill={color}
                fillOpacity={0.12}
              />
            )}
            <LinePath<Row>
              {...props}
              stroke={color}
              strokeWidth={2.5}
              strokeDasharray={
                index ? `${8 - (index % 3)} ${3 + (index % 2)}` : undefined
              }
            />
            {points.map(
              (r, i) =>
                typeof r[v.value] === "number" && (
                  <circle
                    key={i}
                    cx={x(String(r[v.category!]))}
                    cy={y(r[v.value] as number)}
                    r={rows.length > 100 ? 2 : 3.5}
                    fill={color}
                    tabIndex={0}
                    aria-label={`${name}, ${text(r[v.category!])}: ${formatValue(r[v.value], v)}`}
                  >
                    <title>
                      {name} · {text(r[v.category!])}:{" "}
                      {formatValue(r[v.value], v)}
                    </title>
                  </circle>
                ),
            )}
          </g>
        );
      })}
      <text
        x={width / 2}
        y={257}
        textAnchor="middle"
        className="chart-secondary"
      >
        {v.category_label || v.category}
      </text>
      {series.map((name, i) => (
        <g
          key={name}
          transform={`translate(${((i % 4) * width) / 4}, ${278 + Math.floor(i / 4) * 20})`}
        >
          <line
            x1={0}
            x2={15}
            stroke={chartColors[i]}
            strokeWidth={3}
            strokeDasharray={i ? "5 3" : undefined}
          />
          <text x={21} y={4} className="chart-secondary">
            {shorten(name, Math.max(5, Math.floor(width / 4 / 7) - 4))}
          </text>
          <title>{name}</title>
        </g>
      ))}
    </>
  );
}
