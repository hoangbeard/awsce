"""Write results to CSV or JSON files.

The output format follows the file extension: .csv, .json or .html.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FORMATS = {".csv", ".json", ".html"}


class ExportError(ValueError):
    pass


def output_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in FORMATS:
        raise ExportError(f"Unsupported file type {suffix or '(none)'}. Use .csv, .json or .html.")
    return suffix[1:]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, header: list[str], rows: Iterable[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_safe(cell) for cell in row])


def _safe(cell: Any) -> Any:
    """Stop spreadsheet apps from running cell values as formulas (CSV injection).

    Resource names and tags come from AWS accounts and can contain any text.
    """
    if isinstance(cell, float):
        return f"{cell:.4f}".rstrip("0").rstrip(".") if cell else "0"
    if isinstance(cell, str) and len(cell) > 1 and cell[:1] in _FORMULA_START:
        try:
            float(cell)
        except ValueError:
            return "'" + cell
    return cell


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


# Row builders, one per report view ------------------------------------------


def account_rows(accounts: list[dict]) -> tuple[list[str], list[list[Any]]]:
    header = ["profile", "account_id", "service", "usage_type", "quantity", "unit", "cost_usd"]
    rows = [
        [
            a["profile"],
            a["account_id"],
            s["service"],
            u["usage_type"],
            u["quantity"],
            u["unit"],
            u["cost"],
        ]
        for a in accounts
        for s in a["services"]
        for u in s["usage_types"]
    ]
    return header, rows


def service_rows(services: list[dict]) -> tuple[list[str], list[list[Any]]]:
    header = [
        "service",
        "service_total_usd",
        "profile",
        "account_id",
        "account_service_total_usd",
        "usage_type",
        "quantity",
        "unit",
        "cost_usd",
    ]
    rows = [
        [
            s["service"],
            s["total"],
            a["profile"],
            a["account_id"],
            a["total"],
            u["usage_type"],
            u["quantity"],
            u["unit"],
            u["cost"],
        ]
        for s in services
        for a in s["accounts"]
        for u in a["usage_types"]
    ]
    return header, rows


def summary_rows(services: list[dict]) -> tuple[list[str], list[list[Any]]]:
    header = ["service", "usage_type", "quantity", "unit", "unit_price_usd", "accounts", "cost_usd"]
    rows = [
        [
            s["service"],
            u["usage_type"],
            u["quantity"],
            u["unit"],
            u["unit_price"] if u["unit_price"] is not None else "",
            u["account_count"],
            u["cost"],
        ]
        for s in services
        for u in s["usage_types"]
    ]
    return header, rows


def category_rows(report: dict) -> tuple[list[str], list[list[Any]]]:
    header = ["category", "value", "first_seen", "service", "quantity", "unit", "cost_usd"]
    first_seen = report.get("first_seen", {})
    rows = [
        [
            report["category"],
            v["value"],
            first_seen.get(v["value"], ""),
            s["service"],
            s["quantity"],
            s["unit"],
            s["cost"],
        ]
        for v in report["values"]
        for s in v["services"]
    ]
    return header, rows


def rightsizing_rows(recs: list[dict]) -> tuple[list[str], list[list[Any]]]:
    header = [
        "resource_type",
        "resource_id",
        "account_id",
        "region",
        "finding",
        "current_config",
        "recommended_config",
        "current_monthly_cost",
        "recommended_monthly_cost",
        "monthly_savings",
        "savings_percent",
        "currency",
        "resource_arn",
    ]
    return header, [[r.get(h) if r.get(h) is not None else "" for h in header] for r in recs]


def hub_rows(items: list[dict]) -> tuple[list[str], list[list[Any]]]:
    header = [
        "resource_type",
        "resource_id",
        "account_id",
        "region",
        "action",
        "current",
        "recommended",
        "current_monthly_cost",
        "monthly_savings",
        "savings_percent",
        "currency",
        "effort",
        "restart_needed",
        "rollback_possible",
        "resource_arn",
    ]
    return header, [[i.get(h) if i.get(h) is not None else "" for h in header] for i in items]
