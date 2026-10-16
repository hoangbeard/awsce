from conftest import group, period

from awsce import costs


def _cost_response(aws, groups_by_month, token=None, expected=None):
    response = {
        "ResultsByTime": [period(m, e, g) for m, e, g in groups_by_month],
        "DimensionValueAttributes": [],
    }
    if token:
        response["NextPageToken"] = token
    aws.stub("ce").add_response("get_cost_and_usage", response, expected)


def test_fetch_account_costs_merges_months_and_pages(aws):
    expected_first = {
        "TimePeriod": {"Start": "2026-01-01", "End": "2026-03-01"},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost", "UsageQuantity"],
        "GroupBy": [
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
        ],
    }
    _cost_response(
        aws,
        [("2026-01-01", "2026-02-01", [group(["Amazon EC2", "BoxUsage:t3.micro"], "10", "100")])],
        token="page-2",
        expected=expected_first,
    )
    _cost_response(
        aws,
        [
            (
                "2026-02-01",
                "2026-03-01",
                [
                    group(["Amazon EC2", "BoxUsage:t3.micro"], "5", "50"),
                    group(["Amazon S3", "TimedStorage-ByteHrs"], "0.004", "2", "GB-Mo"),
                    group(["Tax", "Tax"], "0", "0"),
                ],
            )
        ],
        expected={**expected_first, "NextPageToken": "page-2"},
    )
    aws.identity("111111111111")

    result = costs.fetch_account_costs(aws.context(), None, "2026-01-01", "2026-03-01")

    assert result["account_id"] == "111111111111"
    assert result["profile"] == "default"
    assert result["months"] == {"2026-01": 10.0, "2026-02": 5.004}
    assert [s["service"] for s in result["services"]] == ["Amazon EC2", "Amazon S3"]
    ec2 = result["services"][0]
    assert ec2["total"] == 15.0
    assert ec2["usage_types"] == [
        {"usage_type": "BoxUsage:t3.micro", "cost": 15.0, "quantity": 150.0, "unit": "Hrs"}
    ]
    assert result["total"] == 15.004


def _account(account_id, profile, services):
    return {
        "account_id": account_id,
        "profile": profile,
        "start": "2026-01-01",
        "end": "2026-02-01",
        "months": {"2026-01": sum(t for _, t, _ in services)},
        "total": sum(t for _, t, _ in services),
        "services": [
            {"service": name, "total": total, "usage_types": rows} for name, total, rows in services
        ],
    }


def _row(usage_type, cost, quantity=0.0, unit=""):
    return {"usage_type": usage_type, "cost": cost, "quantity": quantity, "unit": unit}


def test_filter_hides_cents_but_keeps_credits_and_totals():
    account = _account(
        "1",
        "a",
        [
            ("Amazon S3", 4.995, [_row("Storage", 5.0), _row("Requests", 0.005, 10, "Req")]),
            ("Credits", -3.0, [_row("Credit", -3.0)]),
            ("Tiny", 0.001, [_row("Tiny", 0.001)]),
        ],
    )
    shown = costs.filter_account(account, detail=False)
    assert [s["service"] for s in shown["services"]] == ["Amazon S3", "Credits"]
    assert [u["usage_type"] for u in shown["services"][0]["usage_types"]] == ["Storage"]
    assert shown["services"][0]["total"] == 4.995
    assert shown["total"] == account["total"]

    detailed = costs.filter_account(account, detail=True)
    assert len(detailed["services"]) == 3


def test_by_service_and_summary_across_accounts():
    a = _account("1", "dev", [("Amazon EC2", 10.0, [_row("BoxUsage", 10.0, 100, "Hrs")])])
    b = _account(
        "2",
        "prod",
        [
            ("Amazon EC2", 30.0, [_row("BoxUsage", 30.0, 200, "Hrs")]),
            ("Amazon S3", 1.0, [_row("Storage", 1.0, 4, "GB-Mo")]),
        ],
    )

    grouped = costs.by_service([a, b])
    assert [s["service"] for s in grouped] == ["Amazon EC2", "Amazon S3"]
    assert grouped[0]["total"] == 40.0
    assert [x["profile"] for x in grouped[0]["accounts"]] == ["prod", "dev"]

    summary = costs.summary([a, b])
    box = summary[0]["usage_types"][0]
    assert box["cost"] == 40.0
    assert box["quantity"] == 300
    assert box["account_count"] == 2
    assert box["unit_price"] == 40.0 / 300
    assert costs.grand_total([a, b]) == 41.0


def test_unit_price_edge_cases():
    assert costs.unit_price(0, 10) is None
    assert costs.unit_price(5, 0) is None
    assert costs.unit_price(-1, 10) is None


def test_list_services_paginates(aws):
    ce = aws.stub("ce")
    ce.add_response(
        "get_dimension_values",
        {
            "DimensionValues": [{"Value": "Amazon S3"}],
            "ReturnSize": 1,
            "TotalSize": 2,
            "NextPageToken": "t",
        },
    )
    ce.add_response(
        "get_dimension_values",
        {
            "DimensionValues": [{"Value": "AWS Lambda"}],
            "ReturnSize": 1,
            "TotalSize": 2,
        },
    )
    assert costs.list_services(aws.context(), None, "2026-01-01", "2026-02-01") == [
        "AWS Lambda",
        "Amazon S3",
    ]


def test_cost_category_strips_prefix_and_marks_uncategorized(aws):
    _cost_response(
        aws,
        [
            (
                "2026-01-01",
                "2026-02-01",
                [
                    group(["Team$platform", "Amazon EC2"], "20", "1"),
                    group(["Team$platform", "Amazon S3"], "2", "1"),
                    group(["Team$", "AWS Lambda"], "5", "1"),
                ],
            )
        ],
    )
    aws.identity("222222222222")

    report = costs.fetch_cost_category(aws.context(), None, "Team", "2026-01-01", "2026-02-01")

    assert report["category"] == "Team"
    assert report["total"] == 27.0
    assert [(v["value"], v["total"]) for v in report["values"]] == [
        ("platform", 22.0),
        (costs.UNCATEGORIZED, 5.0),
    ]
    assert costs.filter_category(report, detail=False)["values"] == report["values"]


def test_first_seen(aws):
    _cost_response(
        aws,
        [
            ("2025-11-01", "2025-12-01", [group(["Team$web"], "0")]),
            ("2025-12-01", "2026-01-01", [group(["Team$web"], "3"), group(["Team$api"], "0")]),
            ("2026-01-01", "2026-02-01", [group(["Team$api"], "1"), group(["Team$web"], "4")]),
        ],
    )
    first = costs.fetch_first_seen(aws.context(), None, "Team")
    assert first == {"web": "2025-12", "api": "2026-01"}
