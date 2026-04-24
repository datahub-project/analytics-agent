---
name: publish_analysis
description: >
  Use this skill when the user wants to publish, share, save, or preserve a
  completed data analysis so others in the org can find it. Saves as a versioned
  Analysis document in the DataHub knowledge base, organised under a folder
  hierarchy that reflects whether the content is private, team-scoped, or global.
license: MIT
compatibility: Requires DataHub write-back enabled in Settings → Connections
allowed-tools: search_documents, get_entities, publish_analysis
metadata:
  author: analytics-agent
  version: "1.0"
---

# publish_analysis

## Overview

This skill publishes a completed data analysis as a structured document in
DataHub's hierarchical knowledge base. Before saving, the agent discovers
the org's existing document structure and asks the user how widely the
analysis should be shared.

## Instructions

### Step 1 — Discover the org's document strategy

Call `search_documents` with query `"Analysis"` to find existing analysis
documents. Look at the results and identify any naming patterns or folder
structure the org already uses (e.g. "Analyses / Reports / Q1-2024").

If no existing analysis documents are found, note that you will create a
default hierarchy:
- `Shared → Analyses → Private / {Your Name}` (private)
- `Shared → Analyses → Teams` (team-shared)
- `Shared → Analyses → Reports` (org-wide)

### Step 2 — Ask the user about visibility

Before saving, ask the user:
> "Should this analysis be saved **privately** (only visible to you),
> shared with your **team**, or published **globally** for the whole org?"

Map their answer to the `visibility` parameter:
| Answer | visibility value |
|--------|-----------------|
| Private / just me / personal | `"private"` |
| Team / my team / shared with team | `"team"` |
| Global / everyone / public / org-wide | `"global"` |

### Step 3 — Prepare the document body

Structure the analysis body in markdown using this template:

```
## Summary
<2–3 sentence overview of what was analysed and the top finding>

## Key Findings
- <finding 1>
- <finding 2>
- <finding 3>

## Methodology
<describe the approach: what tables were queried, what logic was applied,
any filters or date ranges used>

## SQL
```sql
<the key query or queries used>
```

## Data Sources
- <dataset URN or name>
- <dataset URN or name>
```

### Step 4 — Collect related dataset URNs

From prior `search` / `get_entities` results, collect URNs of the datasets
that were queried or referenced. Pass these as `related_dataset_urns` so
DataHub links the document back to the relevant assets.

### Step 5 — Call publish_analysis

Call the tool with:
- `title`: clear descriptive title, e.g. "Q1 2024 Revenue by Region"
- `body`: the markdown document prepared in Step 3
- `visibility`: value from Step 2
- `related_dataset_urns`: list from Step 4 (empty list if none)
- `topics`: optional tags, e.g. `["revenue", "q1-2024", "finance"]`

### Step 6 — Report back

After the tool returns, tell the user:
- Whether it succeeded
- The document URN (so they can find it in DataHub)
- Where it was saved (which folder in the hierarchy)
