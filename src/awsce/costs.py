"""Fetch costs from Cost Explorer and shape them for display and export.

All amounts are unblended costs in USD.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .aws import AwsContext, paginate
from .dates import months_back

# Rows below this amount are hidden unless the user asks for --detail.
MIN_COST = 0.01

_METRICS = ["UnblendedCost", "UsageQuantity"]


def _amounts(group: dict[str, Any]) -> tuple[float, float, str]:
    metrics = group.get("Metrics", {})
    cost = float(metrics.get("UnblendedCost", {}).get("Amount", 0) or 0)
    quantity_metric = metrics.get("UsageQuantity", {})
    quantity = float(quantity_metric.get("Amount", 0) or 0)
    return cost, quantity, quantity_metric.get("Unit", "") or ""


def _keep(cost: float, quantity: float, detail: bool) -> bool:
    # abs(): credits and refunds show up as negative costs and should stay visible.
    return (cost != 0 or quantity > 0) if detail else abs(cost) >= MIN_COST


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


def fetch_account_costs(aws: AwsContext, profile: str | None, start: str, end: str) -> dict:
    """Costs for one account (profile), grouped by service and usage type.

    Every row with any cost or usage is kept, so the result can be cached once
    and filtered later with or without --detail.
    """
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    months: dict[str, float] = defaultdict(float)

    pages = paginate(
        aws.ce(profile).get_cost_and_usage,
        "NextPageToken",
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=_METRICS,
        GroupBy=[
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
        ],
    )
    for page in pages:
        for period in page.get("ResultsByTime", []):
            month = period.get("TimePeriod", {}).get("Start", "")[:7]
            for group in period.get("Groups", []):
                keys = group.get("Keys", []) + ["Unknown", "Unknown"]
                service, usage_type = keys[0], keys[1]
                cost, quantity, unit = _amounts(group)
                if cost == 0 and quantity == 0:
                    continue
                row = rows.setdefault(
                    (service, usage_type),
                    {"usage_type": usage_type, "cost": 0.0, "quantity": 0.0, "unit": unit},
                )
                row["cost"] += cost
                row["quantity"] += quantity
                row["unit"] = row["unit"] or unit
                months[month] += cost

    services: dict[str, dict[str, Any]] = {}
    for (service, _), row in rows.items():
        entry = services.setdefault(service, {"service": service, "total": 0.0, "usage_types": []})
        entry["usage_types"].append(row)
        entry["total"] += row["cost"]

    ordered = sorted(services.values(), key=lambda s: s["total"], reverse=True)
    for entry in ordered:
        entry["usage_types"].sort(key=lambda r: r["cost"], reverse=True)

    return {
        "profile": profile or "default",
        "account_id": aws.account_id(profile),
        "start": start,
        "end": end,
        "total": sum(s["total"] for s in ordered),
        "months": dict(sorted(months.items())),
        "services": ordered,
    }


def filter_account(account: dict, detail: bool) -> dict:
    """Drop rows under one cent unless ``detail`` is set. Totals stay exact."""
    services = []
    for service in account["services"]:
        usage = [u for u in service["usage_types"] if _keep(u["cost"], u["quantity"], detail)]
        if usage:
            services.append({**service, "usage_types": usage})
    return {**account, "services": services}


# --------------------------------------------------------------------------
# Views across accounts
# --------------------------------------------------------------------------


def by_service(accounts: list[dict]) -> list[dict]:
    """Service → account → usage types, most expensive first."""
    services: dict[str, dict[str, Any]] = {}
    for account in accounts:
        for service in account["services"]:
            entry = services.setdefault(
                service["service"], {"service": service["service"], "total": 0.0, "accounts": []}
            )
            entry["total"] += service["total"]
            entry["accounts"].append(
                {
                    "account_id": account["account_id"],
                    "profile": account["profile"],
                    "total": service["total"],
                    "usage_types": service["usage_types"],
                }
            )
    result = sorted(services.values(), key=lambda s: s["total"], reverse=True)
    for entry in result:
        entry["accounts"].sort(key=lambda a: a["total"], reverse=True)
    return result


def summary(accounts: list[dict]) -> list[dict]:
    """Service → usage type totals across all accounts, without account details."""
    usage: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for account in accounts:
        for service in account["services"]:
            for row in service["usage_types"]:
                entry = usage[service["service"]].setdefault(
                    row["usage_type"],
                    {
                        "usage_type": row["usage_type"],
                        "cost": 0.0,
                        "quantity": 0.0,
                        "unit": row["unit"],
                        "accounts": set(),
                    },
                )
                entry["cost"] += row["cost"]
                entry["quantity"] += row["quantity"]
                entry["accounts"].add(account["account_id"])

    result = []
    for service, rows in usage.items():
        usage_types = []
        for row in rows.values():
            usage_types.append(
                {
                    "usage_type": row["usage_type"],
                    "cost": row["cost"],
                    "quantity": row["quantity"],
                    "unit": row["unit"],
                    "unit_price": unit_price(row["cost"], row["quantity"]),
                    "account_count": len(row["accounts"]),
                }
            )
        usage_types.sort(key=lambda r: r["cost"], reverse=True)
        result.append(
            {
                "service": service,
                "total": sum(r["cost"] for r in usage_types),
                "usage_types": usage_types,
            }
        )
    return sorted(result, key=lambda s: s["total"], reverse=True)


def unit_price(cost: float, quantity: float) -> float | None:
    """Average price per unit, or None when it cannot be computed."""
    if cost <= 0 or quantity <= 0:
        return None
    return cost / quantity


def grand_total(accounts: list[dict]) -> float:
    return sum(a["total"] for a in accounts)


# --------------------------------------------------------------------------
# Services list
# --------------------------------------------------------------------------


def list_services(aws: AwsContext, profile: str | None, start: str, end: str) -> list[str]:
    """Names of AWS services that have cost or usage in the period."""
    names: set[str] = set()
    for page in paginate(
        aws.ce(profile).get_dimension_values,
        "NextPageToken",
        TimePeriod={"Start": start, "End": end},
        Dimension="SERVICE",
    ):
        names.update(item["Value"] for item in page.get("DimensionValues", []))
    return sorted(names)


# --------------------------------------------------------------------------
# Cost categories
# --------------------------------------------------------------------------

UNCATEGORIZED = "Uncategorized"


def _category_value(raw_key: str, category: str) -> str:
    """Cost Explorer returns keys like "Team$platform"; "Team$" means no match."""
    prefix = f"{category}$"
    if raw_key.startswith(prefix):
        return raw_key[len(prefix) :] or UNCATEGORIZED
    return raw_key or UNCATEGORIZED


def fetch_cost_category(
    aws: AwsContext, profile: str | None, category: str, start: str, end: str
) -> dict:
    """Costs grouped by the values of one AWS Cost Category, then by service."""
    values: dict[str, dict[str, Any]] = {}
    for page in paginate(
        aws.ce(profile).get_cost_and_usage,
        "NextPageToken",
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=_METRICS,
        GroupBy=[
            {"Type": "COST_CATEGORY", "Key": category},
            {"Type": "DIMENSION", "Key": "SERVICE"},
        ],
    ):
        for period in page.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                keys = group.get("Keys", []) + ["", "Unknown"]
                value = _category_value(keys[0], category)
                cost, quantity, unit = _amounts(group)
                if cost == 0 and quantity == 0:
                    continue
                entry = values.setdefault(value, {"value": value, "total": 0.0, "services": {}})
                svc = entry["services"].setdefault(
                    keys[1], {"service": keys[1], "cost": 0.0, "quantity": 0.0, "unit": unit}
                )
                svc["cost"] += cost
                svc["quantity"] += quantity
                entry["total"] += cost

    result = []
    for entry in values.values():
        services = sorted(entry["services"].values(), key=lambda s: s["cost"], reverse=True)
        result.append({"value": entry["value"], "total": entry["total"], "services": services})
    result.sort(key=lambda v: v["total"], reverse=True)

    return {
        "profile": profile or "default",
        "account_id": aws.account_id(profile),
        "category": category,
        "start": start,
        "end": end,
        "total": sum(v["total"] for v in result),
        "values": result,
    }


def filter_category(report: dict, detail: bool) -> dict:
    values = []
    for value in report["values"]:
        services = [s for s in value["services"] if _keep(s["cost"], s["quantity"], detail)]
        if services:
            values.append({**value, "services": services})
    return {**report, "values": values}


def fetch_first_seen(
    aws: AwsContext, profile: str | None, category: str, lookback_months: int = 12
) -> dict[str, str]:
    """First month (YYYY-MM) in which each category value had any cost."""
    start, end = months_back(lookback_months)
    first: dict[str, str] = {}
    for page in paginate(
        aws.ce(profile).get_cost_and_usage,
        "NextPageToken",
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "COST_CATEGORY", "Key": category}],
    ):
        for period in page.get("ResultsByTime", []):
            month = period.get("TimePeriod", {}).get("Start", "")[:7]
            for group in period.get("Groups", []):
                value = _category_value((group.get("Keys") or [""])[0], category)
                cost, _, _ = _amounts(group)
                if cost > 0 and (value not in first or month < first[value]):
                    first[value] = month
    return first
