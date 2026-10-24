import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  isRenderableIntent,
  formatValue,
  numericDomain,
  type VizIntent,
} from "../viz";
import { IntentChart } from "@/components/Charts/IntentChart";
import { buildUiMessages } from "../buildUiMessages";

const intent: VizIntent = {
  version: 1,
  kind: "bar",
  title: "Revenue by region",
  category: "region",
  value: "revenue",
};
const rows = [
  { region: "West", revenue: 100 },
  { region: "East", revenue: -20 },
  { region: "North", revenue: null },
];
describe("visualization boundary", () => {
  it("preserves negative values, zeros, and nulls", () => {
    expect(isRenderableIntent(intent, rows)).toBe(true);
    expect(numericDomain([-20, 100])).toEqual([-20, 100]);
    expect(numericDomain([0, 0])).toEqual([0, 1]);
    expect(formatValue(null, intent)).toBe("No value");
    expect(formatValue(0.25, { ...intent, format: "percent" })).toBe("25%");
  });
  it.each([
    [{ ...intent, version: 2 }, rows],
    [{ ...intent, value: "fake" }, rows],
    [intent, [...rows, ...rows]],
    [intent, [{ region: "West", revenue: Infinity }]],
    [intent, [{ region: "West", revenue: true }]],
    [intent, [{ region: "West", revenue: "12" }]],
    [{ ...intent, format: "fake" }, rows],
    [{ ...intent, currency: "fake" }, rows],
    [intent, [{ region: "West", revenue: null }]],
    [{ ...intent, series: "region" }, rows],
    [{ ...intent, category: "revenue" }, rows],
  ])("rejects malformed or ambiguous data", (spec, data) =>
    expect(isRenderableIntent(spec, data)).toBe(false),
  );
  it("renders signed bars with an explicit zero baseline and null labels", () => {
    const html = renderToStaticMarkup(
      <IntentChart
        payload={{
          viz_intent: intent,
          rows,
          reasoning: "Compare regions",
          chart_type: "bar",
        }}
      />,
    );
    expect(html).toContain("chart-zero");
    expect(html).toContain("No value");
    expect(html).toContain("East: -20");
    expect(html).not.toContain("NaN");
  });
  it("preserves payload through persisted message reconstruction", () => {
    const payload = {
      viz_intent: intent,
      rows,
      reasoning: "Compare",
      chart_type: "bar",
    };
    const { messages } = buildUiMessages(
      JSON.parse(
        JSON.stringify([
          {
            id: "chart",
            role: "assistant",
            event_type: "CHART",
            sequence: 1,
            created_at: "2026-10-23",
            payload,
          },
        ]),
      ),
    );
    expect(messages[0].payload).toEqual(payload);
  });
  it("shows table rather than dropping unsupported saved charts", () => {
    const html = renderToStaticMarkup(
      <IntentChart
        payload={{
          viz_intent: { ...intent, version: 2 } as never,
          rows,
          reasoning: "",
          chart_type: "bar",
        }}
      />,
    );
    expect(html).toContain("<table>");
    expect(html).toContain("West");
  });
  it("does not bridge nulls in line or area charts", () => {
    for (const kind of ["line", "area"] as const) {
      const html = renderToStaticMarkup(
        <IntentChart
          payload={{
            viz_intent: { ...intent, kind },
            rows: [rows[0], rows[2], rows[1]],
            reasoning: "",
            chart_type: kind,
          }}
        />,
      );
      expect(html).not.toContain("NaN");
      expect(html).toContain("East");
      // Each isolated point is a distinct SVG move; no line across the missing value.
      const line = html.match(/class="visx-linepath"[^>]*d="([^"]+)"/);
      expect(line).not.toBeNull();
      expect(line![1].match(/M/g)).toHaveLength(2);
    }
  });
});
