"""Savings recommendations from AWS Compute Optimizer and Cost Optimization Hub.

Both services must be turned on (opted in) in the account before they return data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from .aws import GLOBAL_REGION, AwsContext, paginate


def _config_summary(containers: list[dict]) -> str:
    parts = [
        f"{c.get('containerName', '?')}: {c.get('cpu', '?')} CPU / "
        f"{c.get('memorySizeConfiguration', {}).get('memory', '?')} MiB"
        for c in containers
    ]
    return "; ".join(parts) or "-"


def _volume(cfg: dict) -> str:
    return f"{cfg.get('volumeType', '?')} {cfg.get('volumeSize', '?')} GiB"


@dataclass(frozen=True)
class ResourceType:
    """How to read one Compute Optimizer API."""

    label: str
    method: str
    items_key: str
    options_key: str
    resource_id: Callable[[dict], str]
    arn: Callable[[dict], str]
    current: Callable[[dict], str]
    recommended: Callable[[dict], str]


def _arn_tail(arn: str, sep: str = ":") -> str:
    return arn.rsplit(sep, 1)[-1] if sep in arn else arn


RESOURCE_TYPES: dict[str, ResourceType] = {
    "ec2": ResourceType(
        label="EC2 instance",
        method="get_ec2_instance_recommendations",
        items_key="instanceRecommendations",
        options_key="recommendationOptions",
        resource_id=lambda i: i.get("instanceName") or i.get("instanceArn", "").rsplit("/", 1)[-1],
        arn=lambda i: i.get("instanceArn", ""),
        current=lambda i: i.get("currentInstanceType", "-"),
        recommended=lambda o: o.get("instanceType", "-"),
    ),
    "asg": ResourceType(
        label="Auto Scaling group",
        method="get_auto_scaling_group_recommendations",
        items_key="autoScalingGroupRecommendations",
        options_key="recommendationOptions",
        resource_id=lambda i: i.get("autoScalingGroupName", "-"),
        arn=lambda i: i.get("autoScalingGroupArn", ""),
        current=lambda i: i.get("currentConfiguration", {}).get("instanceType", "-"),
        recommended=lambda o: o.get("configuration", {}).get("instanceType", "-"),
    ),
    "ebs": ResourceType(
        label="EBS volume",
        method="get_ebs_volume_recommendations",
        items_key="volumeRecommendations",
        options_key="volumeRecommendationOptions",
        resource_id=lambda i: _arn_tail(i.get("volumeArn", "-"), "/"),
        arn=lambda i: i.get("volumeArn", ""),
        current=lambda i: _volume(i.get("currentConfiguration", {})),
        recommended=lambda o: _volume(o.get("configuration", {})),
    ),
    "lambda": ResourceType(
        label="Lambda function",
        method="get_lambda_function_recommendations",
        items_key="lambdaFunctionRecommendations",
        options_key="memorySizeRecommendationOptions",
        resource_id=lambda i: _arn_tail(i.get("functionArn", "-")),
        arn=lambda i: i.get("functionArn", ""),
        current=lambda i: f"{i.get('currentMemorySize', '?')} MB",
        recommended=lambda o: f"{o.get('memorySize', '?')} MB",
    ),
    "rds": ResourceType(
        label="RDS / Aurora",
        method="get_rds_database_recommendations",
        items_key="rdsDBRecommendations",
        options_key="instanceRecommendationOptions",
        resource_id=lambda i: _arn_tail(i.get("resourceArn", "-")),
        arn=lambda i: i.get("resourceArn", ""),
        current=lambda i: i.get("currentDBInstanceClass", "-"),
        recommended=lambda o: o.get("dbInstanceClass", "-"),
    ),
    "ecs": ResourceType(
        label="ECS on Fargate",
        method="get_ecs_service_recommendations",
        items_key="ecsServiceRecommendations",
        options_key="serviceRecommendationOptions",
        resource_id=lambda i: _arn_tail(i.get("serviceArn", "-"), "/"),
        arn=lambda i: i.get("serviceArn", ""),
        current=lambda i: _config_summary(
            i.get("currentServiceConfiguration", {}).get("containerConfigurations", [])
        ),
        recommended=lambda o: _config_summary(o.get("containerRecommendations", [])),
    ),
}


def best_option(options: list[dict]) -> tuple[dict, float, float, str]:
    """Pick the option with the highest monthly savings.

    Returns (option, savings, savings_percent, currency). The recommended
    configuration and the savings always come from the same option.
    """
    best: dict = options[0] if options else {}
    best_value, best_pct, currency = 0.0, 0.0, "USD"
    for option in options:
        opportunity = option.get("savingsOpportunity", {})
        savings = opportunity.get("estimatedMonthlySavings", {})
        value = float(savings.get("value", 0) or 0)
        if value > best_value:
            best = option
            best_value = value
            best_pct = float(opportunity.get("savingsOpportunityPercentage", 0) or 0)
            currency = savings.get("currency", "USD")
    return best, best_value, best_pct, currency


def _monthly_costs(savings: float, pct: float) -> tuple[float | None, float | None]:
    """Estimate (current, recommended) monthly cost from savings and its percentage."""
    if savings > 0 and pct > 0:
        current = savings / (pct / 100)
        return current, current - savings
    return None, None


def _parse(kind: ResourceType, item: dict, profile: str, region: str) -> dict:
    option, savings, pct, currency = best_option(item.get(kind.options_key, []))
    current_cost, recommended_cost = _monthly_costs(savings, pct)
    return {
        "resource_type": kind.label,
        "resource_id": kind.resource_id(item),
        "resource_arn": kind.arn(item),
        "account_id": item.get("accountId", "-"),
        "region": region,
        "profile": profile,
        "finding": item.get("finding", "-"),
        "current_config": kind.current(item),
        "recommended_config": kind.recommended(option) if option else "-",
        "current_monthly_cost": current_cost,
        "recommended_monthly_cost": recommended_cost,
        "monthly_savings": savings,
        "savings_percent": pct,
        "currency": currency,
    }


def org_accounts(aws: AwsContext, profile: str | None) -> dict[str, str]:
    """Active accounts in the AWS Organization, as {id: name}. Needs the management account."""
    org = aws.client("organizations", profile, GLOBAL_REGION)
    accounts: dict[str, str] = {}
    for page in paginate(org.list_accounts, "NextToken"):
        for account in page.get("Accounts", []):
            if account.get("Status", account.get("State")) == "ACTIVE":
                accounts[account["Id"]] = account.get("Name", account["Id"])
    return accounts


def rightsizing(
    aws: AwsContext,
    profiles: list[str | None],
    regions: list[str],
    types: list[str],
    account_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Compute Optimizer recommendations for every profile, region and resource type.

    Errors for one profile, region or type are collected, not raised, so one
    missing permission does not hide every other result.
    """
    results: dict[str, dict] = {}
    errors: list[str] = []
    for profile in profiles:
        for region in regions:
            client = aws.client("compute-optimizer", profile, region)
            # Compute Optimizer accepts one account ID per request.
            scopes: list[list[str]] = [[a] for a in account_ids] if account_ids else [[]]
            for key in types:
                kind = RESOURCE_TYPES[key]
                for scope in scopes:
                    params: dict[str, Any] = {"accountIds": scope} if scope else {}
                    try:
                        for page in paginate(getattr(client, kind.method), "nextToken", **params):
                            for item in page.get(kind.items_key, []):
                                rec = _parse(kind, item, profile or "default", region)
                                results.setdefault(rec["resource_arn"] or rec["resource_id"], rec)
                    except ClientError as exc:
                        where = "/".join([profile or "default", region, key, *scope])
                        errors.append(f"{where}: {exc}")

    recommendations = sorted(results.values(), key=lambda r: r["monthly_savings"], reverse=True)
    return {"recommendations": recommendations, "errors": errors}


HUB_FIELDS = {
    "recommendationId": "recommendation_id",
    "accountId": "account_id",
    "region": "region",
    "resourceId": "resource_id",
    "resourceArn": "resource_arn",
    "currentResourceType": "resource_type",
    "actionType": "action",
    "currentResourceSummary": "current",
    "recommendedResourceSummary": "recommended",
    "estimatedMonthlySavings": "monthly_savings",
    "estimatedSavingsPercentage": "savings_percent",
    "estimatedMonthlyCost": "current_monthly_cost",
    "currencyCode": "currency",
    "implementationEffort": "effort",
    "restartNeeded": "restart_needed",
    "rollbackPossible": "rollback_possible",
}


def hub_recommendations(
    aws: AwsContext,
    profile: str | None,
    resource_types: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Cost Optimization Hub recommendations, highest savings first."""
    client = aws.client("cost-optimization-hub", profile, GLOBAL_REGION)
    params: dict[str, Any] = {
        "includeAllRecommendations": False,
        "orderBy": {"dimension": "EstimatedMonthlySavings", "order": "Desc"},
    }
    if resource_types:
        params["filter"] = {"resourceTypes": resource_types}

    items: list[dict] = []
    for page in paginate(client.list_recommendations, "nextToken", **params):
        for raw in page.get("items", []):
            item = {new: raw.get(old) for old, new in HUB_FIELDS.items()}
            item["monthly_savings"] = float(item["monthly_savings"] or 0)
            item["profile"] = profile or "default"
            items.append(item)
            if limit and len(items) >= limit:
                return items
    return items
