"""Versioned, data-bound visualization contract. No model-generated values or code."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VizIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    kind: Literal["kpi", "bar", "diverging_bar", "line", "area"]
    title: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1)
    category: str | None = None
    series: str | None = None
    value_label: str | None = None
    category_label: str | None = None
    format: Literal["number", "percent", "currency"] = "number"
    currency: Literal["USD", "EUR", "GBP", "JPY", "INR"] = "USD"

    @model_validator(mode="after")
    def check_roles(self) -> VizIntent:
        if self.kind != "kpi" and not self.category:
            raise ValueError("A category column is required")
        if self.series and self.kind not in ("line", "area"):
            raise ValueError("Series is only supported for line and area charts")
        roles = [x for x in (self.value, self.category, self.series) if x]
        if len(set(roles)) != len(roles):
            raise ValueError("Column roles must be distinct")
        return self


def validate_binding(intent: VizIntent, rows: list[dict]) -> None:
    if not rows or len(rows) > 5000:
        raise ValueError("Charts require between 1 and 5,000 rows")
    if intent.kind == "kpi" and len(rows) > 1 and not intent.category:
        raise ValueError("A KPI with history requires a category column")
    seen: set[tuple] = set()
    series_values: set = set()
    numeric = 0
    for row in rows:
        value = row.get(intent.value)
        if intent.value not in row:
            raise ValueError("Value column is missing")
        if value is not None:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("Value column must contain finite numbers or null")
            numeric += 1
        keys = []
        for column in (intent.category, intent.series):
            if column:
                v = row.get(column)
                if isinstance(v, bool) or not isinstance(v, (str, int, float)):
                    raise ValueError("Category and series columns must contain labels")
                if isinstance(v, float) and not math.isfinite(v):
                    raise ValueError("Labels must be finite")
                keys.append(str(v))
        if intent.category:
            key = tuple(keys)
            if key in seen:
                raise ValueError("Aggregate duplicate category/series rows in SQL first")
            seen.add(key)
        if intent.series:
            series_values.add(str(row[intent.series]))
    if not numeric:
        raise ValueError("No numeric values to chart")
    if len(series_values) > 8:
        raise ValueError("Use at most eight series")
    if intent.kind in ("bar", "diverging_bar") and len(rows) > 50:
        raise ValueError("Use at most 50 categories for a bar chart")


def build_chart_payload(result: dict, rows: list[dict]) -> dict:
    """Bind full tool/SQL rows, never the model's sample or invented data."""
    reasoning = str(result.get("reasoning", ""))
    if result.get("viz_intent") is not None:
        try:
            intent = VizIntent.model_validate(result["viz_intent"])
            validate_binding(intent, rows)
            return {
                "viz_intent": intent.model_dump(),
                "rows": rows,
                "reasoning": reasoning,
                "chart_type": intent.kind,
            }
        except ValueError:
            return {
                "rows": rows,
                "chart_type": "table",
                "reasoning": reasoning,
                "viz_error": "This result cannot use the requested chart. View the data below.",
            }
    schema = result.get("chart_schema", {})
    if schema and result.get("chart_type"):
        schema = {**schema, "data": {"values": rows}}
    return {
        "vega_lite_spec": schema,
        "reasoning": reasoning,
        "chart_type": result.get("chart_type", ""),
    }
