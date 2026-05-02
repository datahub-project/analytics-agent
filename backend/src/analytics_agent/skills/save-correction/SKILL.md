---
name: save_correction
description: >
  Use this skill when the user identifies that knowledge in DataHub is wrong,
  incomplete, or missing — whether that's a glossary term definition, a domain
  or data product description, a dataset or column description, an existing
  document that needs updating, or a concept that needs a new reference document.
  Also triggered by "fix this description", "update the metadata", "correct the
  definition", "update the glossary", "fix the domain description", or "write that down".
license: MIT
compatibility: Requires DataHub write-back enabled in Settings → Connections
allowed-tools: search, get_entities, list_schema_fields, search_documents, save_correction
metadata:
  author: analytics-agent
  version: "2.0"
---

# save_correction

## Overview

This skill writes correct knowledge back to DataHub. It handles three cases:

| Mode | When to use | Key inputs |
|------|-------------|------------|
| **Entity/field description** | A glossary term, domain, data product, dataset, or column description is wrong, incomplete, or missing | `entity_urn` + `corrected_description` |
| **Update existing doc** | An existing DataHub document has wrong or outdated content | `doc_urn` + `doc_title` + `doc_body` |
| **Create new doc** | No document exists for this concept; needs to be written from scratch | `doc_title` + `doc_body` + `parent_doc_urn` |

Always confirm with the user before writing anything.

---

## Mode 1 — Entity / field description

Supports any DataHub entity type that has a description field:

| Entity type | URN format | How to find the URN |
|---|---|---|
| Glossary term | `urn:li:glossaryTerm:<id>` | `search(filter="entity_type = glossaryTerm")` |
| Domain | `urn:li:domain:<id>` | `search(filter="entity_type = domain")` |
| Data product | `urn:li:dataProduct:<id>` | `search(filter="entity_type = dataProduct")` |
| Dataset | `urn:li:dataset:(...)` | `search` or `get_entities` |
| Column (field) | same dataset URN + `field_path` | `list_schema_fields` on the dataset |

### Step 1 — Confirm the entity URN

The `entity_urn` must come from a prior `search`, `get_entities`, or
`search_business_context` result. Never construct a URN from scratch.

### Step 2 — Fetch the current description

**Glossary term / domain / data product:** Call `get_entities([entity_urn])` and
extract `description` or `properties.description`.

**Dataset-level:** Call `get_entities([entity_urn])` and extract `description`.

**Field-level:** Call `list_schema_fields` on the dataset URN; note the field's
current `description` and exact `fieldPath` value.

If no description exists, note that one will be added.

### Step 3 — Show the user what will change

> **Entity:** `<dataset name>` (`<urn>`)
> **Field:** `<field name>` *(if applicable)*
>
> **Current description:** `<current text, or "(none)">`
>
> **Proposed correction:** `<new description>`
>
> Shall I apply this correction?

Do **not** call `save_correction` until the user confirms.

### Step 4 — Choose operation

| Situation | operation |
|-----------|-----------|
| Replacing wrong/outdated text | `"replace"` (default) |
| Adding a clarifying note | `"append"` |

### Step 5 — Call save_correction

Pass: `entity_urn`, `corrected_description`, `field_path` (if field-level), `operation`.

---

## Mode 2 — Update existing doc

### Step 1 — Retrieve the document

Use the `doc_urn` from a prior `search_documents` result. If you don't have it,
call `search_documents` with the document title or topic to find it.

### Step 2 — Show the diff

Present the existing document title and a summary of what will change. Ask for
confirmation before writing.

### Step 3 — Call save_correction

Pass: `doc_urn`, `doc_title` (may be unchanged), `doc_body` (full updated markdown body).

---

## Mode 3 — Create new doc

### Step 1 — Find the right parent

Before creating, call `search_documents` to find the most relevant existing folder
or document that should be the parent. Examples:

- Fixing docs about "Revenue Metrics" → find the existing "Revenue" or "Finance" folder
- Adding a definition for a specific dataset → find the dataset's documentation folder
- General concept with no clear home → find the top-level "Knowledge Base" or "Data Dictionary" folder

If no suitable parent exists, use the org's top-level shared folder (search for
`"Shared"` or `"Knowledge Base"`). As a last resort, omit `parent_doc_urn` and
the document will be created at the root level.

### Step 2 — Draft the document

Write a well-structured markdown document. Use headings, bullet points, and
code blocks where appropriate. For concept/metric definitions, use this template:

```
## Definition
<clear 1–2 sentence definition>

## How it's calculated
<formula or logic>

## Source tables
- <table name> — <what it contributes>

## Common pitfalls
- <gotcha 1>
- <gotcha 2>
```

Adapt freely — the template is a starting point, not a requirement.

### Step 3 — Confirm with the user

Show: proposed title, target parent folder (name + URN), and the full document body.
Ask for confirmation before writing.

### Step 4 — Call save_correction

Pass: `doc_title`, `doc_body`, `parent_doc_urn` (from Step 1),
`related_entity_urns` (dataset URNs referenced in the doc, if any).

---

## After writing (all modes)

Report back:
- Whether it succeeded
- The URN of the updated/created entity or document
- For docs: the title and parent folder so the user can find it in DataHub
