"""Render self-contained HTML reports.

Templates are autoescaped, and data passed to JavaScript goes through the
``tojson`` filter, so names from AWS cannot inject HTML or script.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from importlib.resources import files

from jinja2 import Environment, PackageLoader

from . import __version__, costs


def _money(value: float) -> str:
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "-"


def _qty(quantity: float, unit: str) -> str:
    return f"{quantity:,.2f} {unit}".strip() if quantity else ""


_env = Environment(
    loader=PackageLoader("awsce", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals.update(money=_money, pct=_pct, qty=_qty, version=__version__)


def _logo() -> str:
    return base64.b64encode(files("awsce").joinpath("assets/logo.svg").read_bytes()).decode()


def _common(start: str, end: str) -> dict:
    return {
        "start": start,
        "end": end,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "logo": _logo(),
    }


def costs_report(accounts: list[dict], top: int = 15) -> str:
    services = costs.summary(accounts)
    months: dict[str, float] = {}
    for account in accounts:
        for month, amount in account["months"].items():
            months[month] = months.get(month, 0.0) + amount
    start = min((a["start"] for a in accounts), default="")
    end = max((a["end"] for a in accounts), default="")
    return _env.get_template("costs.html.j2").render(
        **_common(start, end),
        accounts=sorted(accounts, key=lambda a: a["total"], reverse=True),
        services=services,
        total=costs.grand_total(accounts),
        top_services=[[s["service"], round(s["total"], 2)] for s in services[:top]],
        account_totals=[
            [f"{a['profile']} ({a['account_id']})", round(a["total"], 2)] for a in accounts
        ],
        months=[[m, round(v, 2)] for m, v in sorted(months.items())],
    )


def category_report(report: dict) -> str:
    report = {**report, "first_seen": report.get("first_seen", {})}
    return _env.get_template("category.html.j2").render(
        **_common(report["start"], report["end"]),
        report=report,
        value_totals=[[v["value"], round(v["total"], 2)] for v in report["values"]],
    )
