"""Command-line interface."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, ProfileNotFound
from rich.console import Console

from . import __version__, costs, export, html, optimize, render
from .aws import AwsContext, available_profiles
from .cache import FileCache
from .dates import DateRangeError, resolve_period

app = typer.Typer(
    name="awsce",
    help="Check, summarize and analyze your AWS costs from the command line.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,  # locals can hold credentials
)
optimize_app = typer.Typer(help="Find ways to save money.", no_args_is_help=True)
cache_app = typer.Typer(help="Manage the local cache.", no_args_is_help=True)
app.add_typer(optimize_app, name="optimize")
app.add_typer(cache_app, name="cache")

console = Console()
err = Console(stderr=True)

T = TypeVar("T")


class State:
    verbose = False


# Shared options ---------------------------------------------------------------

Start = Annotated[
    str | None, typer.Option("--start", help="First day, YYYY-MM-DD. Default: 1st of this month.")
]
End = Annotated[
    str | None, typer.Option("--end", help="Day after the last day, YYYY-MM-DD. Default: today.")
]
Profiles = Annotated[
    list[str] | None,
    typer.Option("--profile", "-p", help="AWS profile. Repeat to query several accounts."),
]
AllProfiles = Annotated[
    bool, typer.Option("--all-profiles", help="Query every profile in your AWS config.")
]
Profile = Annotated[str | None, typer.Option("--profile", "-p", help="AWS profile.")]
Detail = Annotated[bool, typer.Option("--detail", help="Also show rows under $0.01.")]
Output = Annotated[
    Path | None, typer.Option("--output", "-o", help="Save to a file: .csv, .json or .html.")
]
Refresh = Annotated[bool, typer.Option("--refresh", help="Ignore the cache and ask AWS again.")]
CacheHours = Annotated[
    float, typer.Option("--cache-hours", help="How long cached results stay valid.")
]


def _profiles(names: list[str] | None, all_profiles: bool) -> list[str | None]:
    if all_profiles:
        found = available_profiles()
        if not found:
            raise typer.BadParameter(
                "No profiles found in your AWS config.", param_hint="--all-profiles"
            )
        return list(found)
    return list(names) if names else [None]


def _cached(cache: FileCache, key: str, hours: float, refresh: bool, fetch: Callable[[], T]) -> T:
    if not refresh:
        hit = cache.get(key, hours)
        if hit is not None:
            if State.verbose:
                err.print(f"[dim]Using cached result {key}[/]")
            return hit
    data = fetch()
    cache.set(key, data)
    return data


def _run(action: Callable[[], None]) -> None:
    """Turn common AWS and input errors into short messages instead of tracebacks."""
    try:
        action()
    except (DateRangeError, export.ExportError) as exc:
        err.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(2) from None
    except ProfileNotFound as exc:
        err.print(f"[red]Error:[/] {exc}. Run `aws configure list-profiles` to see your profiles.")
        raise typer.Exit(1) from None
    except NoCredentialsError:
        err.print(
            "[red]Error:[/] No AWS credentials found. Run `aws configure` or `aws sso login`."
        )
        raise typer.Exit(1) from None
    except ClientError as exc:
        error = exc.response.get("Error", {})
        err.print(
            f"[red]AWS error ({error.get('Code', 'Unknown')}):[/] {error.get('Message', exc)}"
        )
        raise typer.Exit(1) from None
    except BotoCoreError as exc:
        err.print(f"[red]AWS error:[/] {exc}")
        raise typer.Exit(1) from None


def _save(
    path: Path,
    data: Any,
    rows: tuple[list[str], list[list[Any]]],
    html_fn: Callable[[], str] | None,
) -> None:
    fmt = export.output_format(path)
    if fmt == "json":
        export.write_json(path, data)
    elif fmt == "csv":
        export.write_csv(path, *rows)
    elif html_fn is None:
        raise export.ExportError("HTML is not available for this command. Use .csv or .json.")
    else:
        path.write_text(html_fn(), encoding="utf-8")
    console.print(f"[green]Saved[/] {path}")


def _version(value: bool) -> None:
    if value:
        console.print(f"awsce {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show more detail.")] = False,
) -> None:
    """Check, summarize and analyze your AWS costs.

    Uses your normal AWS credentials (profiles, SSO, environment variables).
    Cost Explorer charges $0.01 per API request, so results are cached for 24 hours.
    """
    State.verbose = verbose


# costs ------------------------------------------------------------------------


class View(str, Enum):
    accounts = "accounts"
    services = "services"
    summary = "summary"


@app.command("costs")
def costs_cmd(
    start: Start = None,
    end: End = None,
    profile: Profiles = None,
    all_profiles: AllProfiles = False,
    view: Annotated[
        View,
        typer.Option(
            "--view",
            help="accounts: each account on its own. services: services across accounts. "
            "summary: usage types across accounts, with unit prices.",
        ),
    ] = View.accounts,
    detail: Detail = False,
    output: Output = None,
    refresh: Refresh = False,
    cache_hours: CacheHours = 24,
) -> None:
    """Show costs by service and usage type for one or more accounts."""

    def action() -> None:
        period = resolve_period(start, end)
        if output:
            export.output_format(output)
        aws, cache = AwsContext(), FileCache()
        names = _profiles(profile, all_profiles)
        accounts = []
        for name in names:
            key = FileCache.make_key("costs", profile=name, start=period[0], end=period[1])
            with console.status(f"Fetching costs for {name or 'default profile'}..."):
                try:
                    raw = _cached(
                        cache,
                        key,
                        cache_hours,
                        refresh,
                        functools.partial(costs.fetch_account_costs, aws, name, *period),
                    )
                except (ClientError, BotoCoreError) as exc:
                    if len(names) == 1:
                        raise
                    # With several profiles, one broken profile should not stop the rest.
                    err.print(f"[yellow]Skipped {name}:[/] {exc}", highlight=False)
                    continue
            accounts.append(costs.filter_account(raw, detail))

        if not accounts:
            err.print("[red]No account returned data.[/]")
            raise typer.Exit(1)

        total = costs.grand_total(accounts)
        if view is View.accounts:
            render.accounts(console, accounts)
            data, rows = accounts, export.account_rows(accounts)
        elif view is View.services:
            grouped = costs.by_service(accounts)
            render.services(console, grouped, total)
            data, rows = grouped, export.service_rows(grouped)
        else:
            grouped = costs.summary(accounts)
            render.summary(console, grouped, total)
            data, rows = grouped, export.summary_rows(grouped)

        if len(accounts) > 1:
            console.print(f"[bold]Total across {len(accounts)} accounts: {html._money(total)}[/]")
        if output:
            _save(output, data, rows, lambda: html.costs_report(accounts))

    _run(action)


# services -----------------------------------------------------------------------


@app.command("services")
def services_cmd(
    start: Start = None,
    end: End = None,
    profile: Profile = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a list.")] = False,
) -> None:
    """List the AWS services that have cost or usage in the period."""

    def action() -> None:
        period = resolve_period(start, end)
        names = costs.list_services(AwsContext(), profile, *period)
        if as_json:
            console.print_json(data=names)
        else:
            for name in names:
                console.print(name, markup=False, highlight=False)

    _run(action)


# cost-category --------------------------------------------------------------------


@app.command("cost-category")
def cost_category_cmd(
    category: Annotated[
        str, typer.Argument(help="Name of an AWS Cost Category, for example Team.")
    ],
    start: Start = None,
    end: End = None,
    profile: Profile = None,
    first_seen: Annotated[
        bool,
        typer.Option(
            "--first-seen/--no-first-seen", help="Show the first month each value had cost."
        ),
    ] = True,
    detail: Detail = False,
    output: Output = None,
    refresh: Refresh = False,
    cache_hours: CacheHours = 24,
) -> None:
    """Show costs grouped by the values of an AWS Cost Category, then by service."""

    def action() -> None:
        period = resolve_period(start, end)
        if output:
            export.output_format(output)
        aws, cache = AwsContext(), FileCache()
        with console.status(f"Fetching cost category {category}..."):
            key = FileCache.make_key(
                "category", profile=profile, category=category, start=period[0], end=period[1]
            )
            report = _cached(
                cache,
                key,
                cache_hours,
                refresh,
                lambda: costs.fetch_cost_category(aws, profile, category, *period),
            )
            if first_seen:
                key = FileCache.make_key(
                    "first-seen",
                    profile=profile,
                    category=category,
                    month=datetime.now().strftime("%Y-%m"),
                )
                report["first_seen"] = _cached(
                    cache,
                    key,
                    cache_hours,
                    refresh,
                    lambda: costs.fetch_first_seen(aws, profile, category),
                )
        report = costs.filter_category(report, detail)
        render.category(console, report)
        if output:
            _save(
                output, report, export.category_rows(report), lambda: html.category_report(report)
            )

    _run(action)


# optimize -------------------------------------------------------------------------


def _default_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


@optimize_app.command("rightsizing")
def rightsizing_cmd(
    profile: Profiles = None,
    all_profiles: AllProfiles = False,
    region: Annotated[
        list[str] | None, typer.Option("--region", "-r", help="Region to check. Repeat for more.")
    ] = None,
    resource_type: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            "-t",
            help=f"Resource type: {', '.join(optimize.RESOURCE_TYPES)}. Default: all.",
        ),
    ] = None,
    organization: Annotated[
        bool,
        typer.Option(
            "--organization", help="Use the management account to check every member account."
        ),
    ] = False,
    min_savings: Annotated[
        float, typer.Option("--min-savings", help="Hide savings below this, in USD/month.")
    ] = 1.0,
    output: Output = None,
    refresh: Refresh = False,
    cache_hours: CacheHours = 4,
) -> None:
    """Rightsizing recommendations from AWS Compute Optimizer."""

    def action() -> None:
        types = resource_type or list(optimize.RESOURCE_TYPES)
        unknown = sorted(set(types) - set(optimize.RESOURCE_TYPES))
        if unknown:
            raise typer.BadParameter(f"Unknown type: {', '.join(unknown)}", param_hint="--type")
        if output:
            export.output_format(output)
        profiles = _profiles(profile, all_profiles)
        regions = region or [_default_region()]
        aws, cache = AwsContext(), FileCache()

        def fetch() -> dict:
            account_ids = None
            if organization:
                account_ids = sorted(optimize.org_accounts(aws, profiles[0]))
                return optimize.rightsizing(aws, profiles[:1], regions, types, account_ids)
            return optimize.rightsizing(aws, profiles, regions, types)

        key = FileCache.make_key(
            "rightsizing",
            profiles=profiles,
            regions=sorted(regions),
            types=sorted(types),
            organization=organization,
        )
        with console.status("Fetching Compute Optimizer recommendations..."):
            result = _cached(cache, key, cache_hours, refresh, fetch)
        recs = [r for r in result["recommendations"] if r["monthly_savings"] >= min_savings]
        render.rightsizing(console, recs)
        for message in result["errors"]:
            err.print(f"[yellow]Warning:[/] {message}", markup=True, highlight=False)
        if output:
            _save(output, recs, export.rightsizing_rows(recs), None)

    _run(action)


@optimize_app.command("hub")
def hub_cmd(
    profile: Profile = None,
    resource_type: Annotated[
        list[str] | None,
        typer.Option(
            "--type", "-t", help="Cost Optimization Hub resource type, for example Ec2Instance."
        ),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", help="Show at most this many recommendations.")
    ] = 50,
    min_savings: Annotated[
        float, typer.Option("--min-savings", help="Hide savings below this, in USD/month.")
    ] = 0.0,
    output: Output = None,
    refresh: Refresh = False,
    cache_hours: CacheHours = 4,
) -> None:
    """Savings recommendations from AWS Cost Optimization Hub."""

    def action() -> None:
        if output:
            export.output_format(output)
        aws, cache = AwsContext(), FileCache()
        key = FileCache.make_key(
            "hub", profile=profile, types=sorted(resource_type or []), limit=limit
        )
        with console.status("Fetching Cost Optimization Hub recommendations..."):
            items = _cached(
                cache,
                key,
                cache_hours,
                refresh,
                lambda: optimize.hub_recommendations(aws, profile, resource_type, limit),
            )
        items = [i for i in items if i["monthly_savings"] >= min_savings]
        render.hub(console, items)
        if output:
            _save(output, items, export.hub_rows(items), None)

    _run(action)


# cache --------------------------------------------------------------------------------


@cache_app.command("list")
def cache_list() -> None:
    """List cached results."""
    cache = FileCache()
    entries = cache.entries()
    if not entries:
        console.print(f"Cache is empty ({cache.directory}).")
        return
    for entry in entries:
        created = datetime.fromtimestamp(entry.created).strftime("%Y-%m-%d %H:%M")
        console.print(f"{created}  {entry.kind:<12} {entry.size / 1024:7.1f} KiB  {entry.key}")
    total = sum(e.size for e in entries) / 1024
    console.print(f"{len(entries)} entries, {total:.1f} KiB in {cache.directory}")


@cache_app.command("clear")
def cache_clear(
    older_than: Annotated[
        float | None,
        typer.Option("--older-than", help="Only remove entries older than this many days."),
    ] = None,
) -> None:
    """Remove cached results."""
    removed = FileCache().clear(older_than)
    console.print(f"Removed {removed} cached entries.")
