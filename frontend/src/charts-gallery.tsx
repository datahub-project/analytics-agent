// Standalone development gallery. Uses the production message component and sample fixtures.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { ChartMessage } from "./components/Chat/messages/ChartMessage";
import type { ChartPayload } from "./types";
import "./index.css";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"];
const trend = months.map((month, i) => ({
  month,
  revenue: [84000, 91000, 87000, 109000, 118000, 132000][i],
}));
const fixtures: ChartPayload[] = [
  {
    viz_intent: {
      version: 1,
      kind: "kpi",
      title: "Monthly recurring revenue",
      category: "month",
      value: "revenue",
      format: "currency",
    },
    rows: trend,
    chart_type: "kpi",
    reasoning: "June revenue, with the last six months for context.",
  },
  {
    viz_intent: {
      version: 1,
      kind: "bar",
      title: "Revenue by region",
      category: "region",
      value: "revenue",
      format: "currency",
      value_label: "Revenue (USD)",
    },
    rows: [
      { region: "North America", revenue: 132000 },
      { region: "Europe", revenue: 98000 },
      { region: "Asia Pacific", revenue: 74000 },
      { region: "Latin America", revenue: 31000 },
    ],
    chart_type: "bar",
    reasoning:
      "North America leads this sample. Each bar represents one region.",
  },
  {
    viz_intent: {
      version: 1,
      kind: "line",
      title: "Growth across plans",
      category: "month",
      value: "accounts",
      series: "plan",
      value_label: "Active accounts",
    },
    rows: months.flatMap((month, i) => [
      { month, plan: "Enterprise", accounts: [80, 92, null, 111, 127, 146][i] },
      { month, plan: "Team", accounts: [42, 51, 65, 72, 78, 91][i] },
    ]),
    chart_type: "line",
    reasoning: "March Enterprise data is missing; the line leaves a gap.",
  },
  {
    viz_intent: {
      version: 1,
      kind: "area",
      title: "Revenue over time",
      category: "month",
      value: "revenue",
      format: "currency",
    },
    rows: trend,
    chart_type: "area",
    reasoning: "Ordered monthly revenue from the sample result.",
  },
  {
    viz_intent: {
      version: 1,
      kind: "diverging_bar",
      title: "Movement against target",
      category: "team",
      value: "delta",
      format: "percent",
      value_label: "Difference from target",
    },
    rows: [
      { team: "Platform", delta: 0.18 },
      { team: "Analytics", delta: 0.09 },
      { team: "Integrations", delta: 0 },
      { team: "Operations", delta: -0.12 },
    ],
    chart_type: "diverging_bar",
    reasoning:
      "The zero baseline separates above-target and below-target results.",
  },
  {
    vega_lite_spec: {
      mark: "bar",
      encoding: {
        x: { field: "month", type: "ordinal" },
        y: { field: "revenue", type: "quantitative" },
      },
      data: { values: trend },
    },
    chart_type: "bar",
    reasoning: "An existing Vega-Lite conversation still renders and exports.",
  },
];
function Gallery() {
  const [theme, setTheme] = useState("datahub");
  return (
    <main
      data-theme={theme}
      style={{
        background: "hsl(var(--muted))",
        color: "hsl(var(--foreground))",
        minHeight: "100vh",
        padding: "clamp(16px, 4vw, 48px)",
      }}
    >
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <header
          style={{
            marginBottom: 32,
            display: "flex",
            gap: 20,
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <div>
            <p style={{ fontSize: 13, color: "hsl(var(--muted-foreground))" }}>
              Analytics Agent / Visualization gallery
            </p>
            <h1 style={{ fontSize: 32, fontWeight: 600, margin: "8px 0" }}>
              From answer to understanding.
            </h1>
            <p>
              Production React charts with sample data. Explore values, tables,
              and exports.
            </p>
          </div>
          <label>
            Theme{" "}
            <select
              aria-label="Theme"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              style={{
                background: "hsl(var(--background))",
                padding: 8,
                borderRadius: 6,
              }}
            >
              {["datahub", "warm", "carbon", "ocean"].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
        </header>
        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fit, minmax(min(100%, 460px), 1fr))",
            gap: 24,
            alignItems: "start",
          }}
        >
          {fixtures.map((payload, i) => (
            <ChartMessage key={i} payload={payload} />
          ))}
        </div>
      </div>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Gallery />
  </React.StrictMode>,
);
