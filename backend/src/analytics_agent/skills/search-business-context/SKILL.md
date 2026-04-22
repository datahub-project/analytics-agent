---
name: search_business_context
description: >
  Call this FIRST whenever the user's question names a business concept, metric,
  or domain (e.g. revenue, churn, active seller, delivery SLA, marketing,
  orders). Searches DataHub documentation, glossary terms, domains, and data
  products in one call and returns authoritative definitions — so you know the
  correct filters, table choice, and calculation logic before writing any SQL.
metadata:
  author: analytics-agent
  version: "1.0"
---

## Business Context Search

Run this workflow **before writing SQL** any time the user's question involves a
named business concept, metric, domain area, or data product — e.g. "revenue",
"churn", "active seller", "marketing domain", "orders data product".

Do **not** skip this to go straight to `list_tables` or `execute_sql`. Business
definitions constrain which tables are authoritative and which filters apply.

---

### Step 1 — Search documentation (always first)

Call `search_documents` with the key term(s) from the user's question.

```
search_documents(query="<term>", num_results=5)
```

Documentation is the highest-authority source: if a doc names a specific table
or defines a calculation rule, follow it. Only deviate with a concrete,
metadata-backed reason.

---

### Step 2 — Look up glossary definitions

If the user used a named metric or business term (MAU, net ARR, churn rate,
seller quality, etc.), search the glossary for its definition:

```
search(query="<term>", filter="entity_type = glossaryTerm", num_results=10)
```

Glossary terms carry the authoritative definition of what a metric means, which
filters apply (e.g. `deleted_at IS NULL` for active records), and sometimes
point to the canonical table. Always read the description of any matching term
via `get_entities` before proceeding.

---

### Step 3 — Find the relevant domain (when the question has a domain flavour)

If the user mentions a business area ("marketing", "finance", "supply chain",
"seller operations") or you need to narrow which datasets are authoritative,
list the matching domains:

```
search(query="<area>", filter="entity_type = domain", num_results=10)
```

Once you have a domain URN, you can scope downstream searches:

```
search(query="<term>", filter="domain = <domain_urn> AND entity_type = dataset", num_results=20)
```

Datasets inside the matching domain are preferred over equally-named datasets
outside it.

---

### Step 4 — Check for data products

Data products are the curated, governed surfaces within a domain — use them to
identify the intended query tables when they exist:

```
search(query="<term>", filter="entity_type = dataProduct", num_results=10)
```

If a matching data product exists, call `get_entities` on its URN to read its
description and linked datasets. Datasets inside a data product are the
highest-confidence query surfaces — prefer them over raw tables with the same
name.

---

### Using the results

| Source | What it tells you |
|---|---|
| `search_documents` | Authoritative business rules, table selection guidance, calculation logic |
| Glossary term description | Metric definition, filter conditions, column-level semantics |
| Domain datasets | Which tables are governed and intended for this area |
| Data product datasets | The curated, production-grade query surfaces |

**Cite what you find.** When you recommend a table or write a query, reference
the doc, glossary term, or data product that led you there. If documentation
and catalog results disagree, state the conflict explicitly and resolve it
before proceeding.

**If nothing is found**, note the gap and proceed with catalog search
(`search` + `get_entities`), but flag to the user that no governed definition
exists. After answering, suggest using `/improve-context` to capture what you
learned.
