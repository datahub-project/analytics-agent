---
name: check_data_quality
description: >
  Call this whenever the user asks about a dataset's trustworthiness, freshness,
  staleness, known data-quality issues (negative values, NULLs, out-of-range), or
  before querying a table that may be stale or known-broken. Reads DataHub
  assertions for the candidate table(s) and surfaces any FAILING freshness or
  quality checks so you reason about stale / planted-bug data before writing SQL —
  instead of blindly trusting a table that is known to lag its source.
metadata:
  author: analytics-agent
  version: "1.0"
---

## Data Quality & Freshness Check

Run this workflow **before writing SQL** any time the question involves staleness,
freshness, trust, or a known data-quality problem on a specific table (e.g. "how many
rows have a negative amount", "is this mart behind its source", "is this table
trustworthy", "how stale is X").

Do **not** skip this to go straight to `list_tables` or `execute_sql`. Assertions are the
DataHub-native signal for known-broken or stale data.

---

### Step 1 — Resolve the candidate dataset URN

From the tables you've already discovered via `search` / `get_entities`, call
`get_dataset_assertions` for each candidate mart/table the question targets:

```
get_dataset_assertions(urn="<dataset_urn>", count=10)
```

`dataset_urn` is the `urn:li:dataset:(...)` from your earlier catalog lookups.

### Step 2 — Read the assertion summary

For each assertion returned, note `type` (e.g. `FRESHNESS`, `VOLUME`, `FIELD`), the
`latestResultType` (`SUCCESS` / `FAILURE` / `NO_RUN`), and the description.

- A **`FRESHNESS` assertion with `FAILURE`** means the table lags its source — the
  freshness SLA was breached. For staleness questions this is the signal to compute the
  lag between the raw source and the mart.
- A **`VOLUME` / `FIELD` assertion with `FAILURE`** means a known data-quality problem is
  planted in this table (e.g. negative amounts, NULL names) — exactly the kind of
  "planted bug" question you should answer directly.

### Step 3 — Fold the signal into the query

- For **staleness / days-behind** questions: the failing freshness assertion tells you
  *which* table is stale. Query both the raw source and the mart, and compute the
  difference (e.g. `julianday(max(raw_ts)) - julianday(max(mart_date))`) — preferring
  `julianday`/`date()` over `CAST(... AS DATE)`, which is unreliable for text dates.
- For **data-quality count** questions: use the failing assertion as confirmation that a
  filter like `WHERE amount < 0` is the right answer surface.

**Cite what you find.** When you answer a staleness or quality question, reference the
assertion that led you there. If a table has no assertions, say so and note the gap
(suggest `/improve-context`).

