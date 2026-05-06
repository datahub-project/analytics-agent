---
name: improve_context
description: Use this skill when the user types /improve-context or asks to capture learnings, improve documentation, or enrich the knowledge base based on this conversation.
metadata:
  author: talkster
  version: "1.0"
---

## /improve-context Workflow

When the user types `/improve-context` (or asks to "capture learnings", "improve docs", "build on this conversation", or similar), execute this workflow:

### Step 1 — Identify gaps from this conversation

Review the full conversation history and identify:
- **Missing documentation**: Topics, metrics, or business concepts the user had to explain manually
- **Ambiguous tables or columns**: Cases where you were uncertain which table to use, or had to ask for clarification
- **Failed context lookups**: Places where `search_documents` or `search` returned no results for a topic that clearly has domain knowledge behind it
- **SQL errors from schema confusion**: Queries that failed because column names, data types, or table relationships were unclear
- **Human corrections**: Cases where the user pointed out a wrong table, wrong definition, or wrong interpretation

Look at patterns across the full conversation, not just the last message. The goal is to identify the *root cause* of struggles — usually a documentation or metadata gap.

### Step 2 — Probe for existing documentation

For each significant gap you identified, call `search_documents` with the relevant topic or term to check:
- Does a document already exist that covers this gap?
- If yes, is it complete, or is it missing the specific detail that caused confusion?

This step is important: don't propose creating a document that already exists. Prefer proposing updates to existing docs over creating new ones when the topic is already covered.

### Step 3 — Draft improvement proposals

Based on your findings, draft 3–5 concrete, numbered improvement proposals. Each proposal should be one of:
- **New doc**: A new document that doesn't exist yet (e.g. "How to analyze churn", a definition guide for "net ARR")
- **Update existing doc**: Add missing detail to a document that already exists
- **Fix description**: Correct or enrich a dataset or column description that was wrong, incomplete, or missing

Format each proposal clearly, like this:

    1. [New doc] "Revenue Metrics Guide" — Define net ARR vs gross ARR and specify that the `revenue` table is the source of truth for ARR calculations.
    2. [Update doc] "Orders FAQ" — Add: `deleted_at IS NULL` means the order is active; non-null means soft-deleted.
    3. [Fix description] `orders.status` column — Current description is empty. Propose: values are 'pending', 'confirmed', 'shipped', 'cancelled', 'refunded'.

Keep each proposal to 1–2 sentences. Be specific about what to add or change.

### Step 4 — Present proposals via tool

Call `present_proposals` with a short framing `prompt` and the `proposals` list you drafted in Step 3. The UI will render a review card with checkboxes — do **not** print a markdown numbered list yourself.

Each proposal must include:
- `id`: a string like `"1"`, `"2"`, `"3"` matching the Step 3 draft order
- `kind`: one of `"new_doc"`, `"update_doc"`, `"fix_description"`
- `title`: short label (e.g. `"Revenue Metrics Guide"`)
- `detail`: 1–2 sentence description of what to add or change
- `target` (optional): `{"urn": "...", "field_path": "..."}` for fix_description proposals that target a known entity
- `write_mode`: `"needs_approval"` for changes to shared DataHub metadata
  (column descriptions, glossary terms, team/global docs — anything other
  users will see), or `"direct"` for user-scoped changes (private docs,
  personal notes, agent memory). The UI renders this as a badge so the user
  sees the blast radius before submitting. Default to `"needs_approval"`
  unless you can clearly establish the change is scoped to the user only.

Example call:
```
present_proposals(
    prompt="I found 3 documentation improvements based on our conversation:",
    proposals=[
        {"id": "1", "kind": "new_doc", "title": "Revenue Metrics Guide",
         "detail": "Define net ARR vs gross ARR and specify the revenue table as source of truth."},
        {"id": "2", "kind": "update_doc", "title": "Orders FAQ",
         "detail": "Add: deleted_at IS NULL means the order is active; non-null means soft-deleted."},
        {"id": "3", "kind": "fix_description", "title": "orders.status column",
         "detail": "Current description is empty. Values: pending, confirmed, shipped, cancelled, refunded.",
         "target": {"urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,orders,PROD)", "field_path": "status"}},
    ]
)
```

Do **not** call any write-back tools until the user explicitly selects proposals and submits.

#### Refining proposals via the in-card chat

The proposals card includes a chat input so the user can ask follow-ups
("explain #2 more", "add one about X", "drop #3"). Those messages arrive
with `source: "proposal_chat"` and an `origin_message_id` pointing back to
the original proposals card. When you receive one:

- If the user wants clarification only, answer briefly in plain text — do
  not re-emit the card.
- If the user wants to add, drop, or restructure proposals, call
  `present_proposals` again with the revised list. A new card will appear;
  the prior card remains in the transcript for context.

### Step 5 — Execute approved changes directly

> **Note: the user has already approved these changes via the proposals card; do NOT ask for another confirmation.**

The user's submission of the proposals card is the final confirmation. Do **NOT** ask for any further confirmation. Do **NOT** print the doc body for review before writing.

For each approved proposal (and only the approved ones, in order):

1. **Draft the full content now:**
   - `new_doc` → write the full markdown body using the template from `save_correction` Mode 3 Step 2. Find the parent folder via `search_documents`.
   - `update_doc` → fetch the existing doc with `search_documents` or `get_entities`, produce the full updated body.
   - `fix_description` → compose the corrected description text.

2. **Call `save_correction` immediately** with the drafted content. **Skip the in-skill confirmation sub-steps** (Mode 1 Step 3, Mode 2 Step 2, Mode 3 Step 3). Collect the result (success + URN, or error message).

3. Do not write any interim "I'm working on it" text between `save_correction` calls. Proceed silently through all selected proposals.

After all writes complete, call `report_proposal_results` **once** with the full list of outcomes. This is the **final action of the turn**. Do **NOT** output any text after calling `report_proposal_results` — no narrative summary, no restating of what succeeded/failed, no "Here's what happened", no bullet list of results. The card rendered from the tool call IS the complete summary; any additional text is redundant noise that will be stripped.

### Step 6 — Graceful degradation (write-back not available)

If `save_correction` is not available (write-back not enabled), still complete
Steps 1–4 fully. At Step 5, instead of calling tools, present the complete
proposed document bodies as markdown the user can copy. Include a note:

> DataHub write-back is not enabled — copy these and add them manually, or enable it in Settings → Connections.
