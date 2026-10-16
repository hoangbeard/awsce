"""Rich tables for the terminal."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .html import _money as money


def _e(value: object) -> str:
    """Escape text from AWS so Rich does not read it as markup."""
    return escape(str(value if value is not None else "-"))


def _qty(quantity: float, unit: str) -> str:
    return f"{quantity:,.2f} {unit}".strip() if quantity else ""


def _table(title: str, *columns: tuple[str, str]) -> Table:
    table = Table(title=title, title_justify="left", header_style="bold", show_lines=False)
    for name, justify in columns:
        table.add_column(name, justify=justify)  # type: ignore[arg-type]
    return table


def accounts(console: Console, data: list[dict]) -> None:
    for account in data:
        table = _table(
            f"{_e(account['profile'])} · account {_e(account['account_id'])}"
            f" · {money(account['total'])}",
            ("Service / usage type", "left"),
            ("Usage", "right"),
            ("Cost", "right"),
        )
        for service in account["services"]:
            table.add_row(
                f"[bold]{_e(service['service'])}[/]", "", f"[bold]{money(service['total'])}[/]"
            )
            for row in service["usage_types"]:
                table.add_row(
                    f"  {_e(row['usage_type'])}",
                    _qty(row["quantity"], row["unit"]),
                    money(row["cost"]),
                )
        console.print(table)


def services(console: Console, data: list[dict], total: float) -> None:
    table = _table(
        f"Cost by service across accounts · {money(total)}",
        ("Service / account", "left"),
        ("Usage types", "right"),
        ("Cost", "right"),
    )
    for service in data:
        table.add_row(
            f"[bold]{_e(service['service'])}[/]", "", f"[bold]{money(service['total'])}[/]"
        )
        for account in service["accounts"]:
            table.add_row(
                f"  {_e(account['profile'])} ({_e(account['account_id'])})",
                str(len(account["usage_types"])),
                money(account["total"]),
            )
    console.print(table)


def summary(console: Console, data: list[dict], total: float) -> None:
    table = _table(
        f"Service summary across accounts · {money(total)}",
        ("Service / usage type", "left"),
        ("Usage", "right"),
        ("Unit price", "right"),
        ("Accounts", "right"),
        ("Cost", "right"),
    )
    for service in data:
        table.add_row(
            f"[bold]{_e(service['service'])}[/]", "", "", "", f"[bold]{money(service['total'])}[/]"
        )
        for row in service["usage_types"]:
            price = row["unit_price"]
            table.add_row(
                f"  {_e(row['usage_type'])}",
                _qty(row["quantity"], row["unit"]),
                f"${price:,.4f}" if price is not None else "",
                str(row["account_count"]),
                money(row["cost"]),
            )
    console.print(table)


def category(console: Console, report: dict) -> None:
    first_seen = report.get("first_seen", {})
    table = _table(
        f"Cost category {_e(report['category'])} · account {_e(report['account_id'])}"
        f" · {money(report['total'])}",
        ("Value / service", "left"),
        ("First seen", "left"),
        ("Cost", "right"),
    )
    for value in report["values"]:
        table.add_row(
            f"[bold]{_e(value['value'])}[/]",
            first_seen.get(value["value"], ""),
            f"[bold]{money(value['total'])}[/]",
        )
        for service in value["services"]:
            table.add_row(f"  {_e(service['service'])}", "", money(service["cost"]))
    console.print(table)


def rightsizing(console: Console, recs: list[dict]) -> None:
    total = sum(r["monthly_savings"] for r in recs)
    table = _table(
        f"Rightsizing recommendations · {len(recs)} · up to {money(total)}/month",
        ("Type", "left"),
        ("Resource", "left"),
        ("Account", "left"),
        ("Region", "left"),
        ("Finding", "left"),
        ("Current", "left"),
        ("Recommended", "left"),
        ("Savings/month", "right"),
    )
    for r in recs:
        table.add_row(
            *(
                _e(r[k])
                for k in (
                    "resource_type",
                    "resource_id",
                    "account_id",
                    "region",
                    "finding",
                    "current_config",
                    "recommended_config",
                )
            ),
            money(r["monthly_savings"]),
        )
    console.print(table)


def hub(console: Console, items: list[dict]) -> None:
    total = sum(i["monthly_savings"] for i in items)
    table = _table(
        f"Cost Optimization Hub · {len(items)} recommendations · up to {money(total)}/month",
        ("Type", "left"),
        ("Resource", "left"),
        ("Account", "left"),
        ("Region", "left"),
        ("Action", "left"),
        ("Effort", "left"),
        ("Savings/month", "right"),
    )
    for i in items:
        table.add_row(
            *(
                _e(i[k])
                for k in (
                    "resource_type",
                    "resource_id",
                    "account_id",
                    "region",
                    "action",
                    "effort",
                )
            ),
            money(i["monthly_savings"]),
        )
    console.print(table)
