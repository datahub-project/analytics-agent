---
name: improve_context
description: Use this skill when the user types /improve-context or asks to capture learnings, improve documentation, or enrich the knowledge base based on this conversation.
metadata:
  author: analytics-agent
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

### Step 4 — Ask for approval

Present the numbered list and ask: **"Which of these would you like me to publish? Reply with the numbers, 'all', or 'none'."**

Do NOT call any write-back tools until the user explicitly approves.

### Step 5 — Execute approved changes

For each approved proposal, follow the `save_correction` skill instructions to
confirm the change with the user before writing:

- **New doc** → Use `save_correction` Mode 3: find the right parent folder first
  via `search_documents`, then call with `doc_title`, `doc_body`, `parent_doc_urn`
- **Update existing doc** → Use `save_correction` Mode 2: call with `doc_urn`,
  `doc_title`, `doc_body` (full updated body)
- **Fix description** → Use `save_correction` Mode 1: call with `entity_urn`,
  `corrected_description`, and `field_path` if field-level

After each write, report the URN and location so the user can find it in DataHub.

### Step 6 — Graceful degradation (write-back not available)

If `save_correction` is not available (write-back not enabled), still complete
Steps 1–4 fully. At Step 5, instead of calling tools, present the complete
proposed document bodies as markdown the user can copy. Include a note:

> DataHub write-back is not enabled — copy these and add them manually, or enable it in Settings → Connections.
