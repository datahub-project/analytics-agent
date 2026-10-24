# React visualizations

The chart model now prefers a versioned `viz_intent` referencing actual result columns.
The server validates that intent and attaches the full returned rows. Both `create_chart`
and the automatic SQL chart node use the same builder. The intent and rows travel in the
CHART event and persist in the existing message JSON, requiring no database migration.

## Catalog

- `kpi`: one value, or the final row of ordered history with a sparkline.
- `bar`: horizontal category comparison.
- `diverging_bar`: signed category comparison with a zero baseline.
- `line`, `area`: ordered categories, optionally grouped by a series column.

Components use visx scales and shapes, with a local adapter of DataHub Alchemy colors.
This does not depend on a published Alchemy package or import DataHub's Ant Design shell.
Chrome follows the app's four themes; printable charts use a light palette.

## Contract

```json
{
  "viz_intent": {
    "version": 1,
    "kind": "bar",
    "title": "Revenue by region",
    "category": "region",
    "value": "revenue",
    "format": "currency",
    "currency": "USD"
  },
  "rows": [{"region": "Europe", "revenue": 98000}],
  "chart_type": "bar",
  "reasoning": "Compare regional revenue."
}
```

Optional roles: `series` (line/area only), `category_label`, and `value_label`.
Formats: number, percent (0.25 means 25%), currency (USD/EUR/GBP/JPY/INR).
Category order is the SQL result order, with equal spacing; time intervals are not inferred.
Aggregate and order in SQL. Duplicate category/series pairs are rejected rather than
silently combined. Null values are missing observations, never zero. Numeric strings
are rejected rather than coerced. Bars are limited to 50 rows, series to eight, and
native charts to 5,000 rows. Known truncated SQL results show a warning.

Invalid or future intents show the returned data as a table. Existing `vega_lite_spec`
messages retain the legacy renderer. Unsupported forms (scatter, heatmap, pie,
stacked/grouped bars, complex transforms, custom color requests) use the Vega prompt
fallback. There is no extra model request and no remote chart asset fetch for native charts.

## Interaction and export

Every native chart has Chart/Data controls and a PNG download. Exact values are
available in the table and SVG labels/titles. Line series also use dash patterns.
PNG export embeds computed theme styles and rasterizes SVG at 2x resolution, including
a title. Browser printing keeps charts visible even when Data is selected and hides
controls; existing full-transcript printing continues to own page assembly.

## Local gallery

From this worktree:

```sh
pnpm --dir frontend dev --host 127.0.0.1 --port 5187
```

Open `http://127.0.0.1:5187/charts.html`. The gallery imports the production message
component with sample fixtures, including a legacy Vega chart and missing trend data.
It is a Vite development entry, not a production app route.

## Verification

- 23 offline backend tests: column binding and validation, mocked model responses for
  both generation paths, SSE payload preservation, legacy fallback, SQLite save/reload.
- 16 new frontend tests: validation, signed/zero/null values, gaps in SVG paths,
  formatting, future-version table fallback, and persisted message reconstruction.
- Production build, changed-file lint, and existing grouping/stress tests pass.
- Browser checks: light/dark themes, 390px mobile width, table toggle, legacy Vega,
  PNG download and inspection of the generated PNG.
- Existing full frontend suite has an unrelated failing test in
  `buildUiMessages.test.ts`: usage attachment to a previous TOOL_CALL. The implementation
  and test were unchanged by this feature.
- No live LLM or warehouse calls were used. Full transcript PDF output still needs a
  manual end-to-end check; print styles were reviewed but a PDF was not generated.
