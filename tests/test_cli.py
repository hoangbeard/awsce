import json

import pytest
from conftest import group, period
from typer.testing import CliRunner

from awsce import cli
from awsce.aws import AwsContext

runner = CliRunner()


@pytest.fixture
def stubbed_cli(aws, monkeypatch):
    monkeypatch.setattr(cli, "AwsContext", lambda: AwsContext(factory=aws.factory))
    return aws


def _costs(aws, profile=None, account="111111111111", cost="12.5"):
    aws.stub("ce", profile).add_response(
        "get_cost_and_usage",
        {
            "ResultsByTime": [
                period(
                    "2026-01-01", "2026-02-01", [group(["Amazon EC2", "BoxUsage"], cost, "100")]
                ),
            ]
        },
    )
    aws.identity(account, profile)


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("awsce ")


def test_costs_exports_csv_and_uses_cache(stubbed_cli, tmp_path):
    _costs(stubbed_cli)
    out = tmp_path / "costs.csv"
    args = ["costs", "--start", "2026-01-01", "--end", "2026-02-01", "-o", str(out)]

    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0, first.output
    assert "Amazon EC2" in first.output
    assert "BoxUsage" in out.read_text()

    # Second run is served from the cache: no new stubbed responses are needed.
    second = runner.invoke(cli.app, args)
    assert second.exit_code == 0, second.output


def test_costs_summary_view_two_profiles_html(stubbed_cli, tmp_path):
    _costs(stubbed_cli, "dev", "111111111111", "10")
    _costs(stubbed_cli, "prod", "222222222222", "30")
    out = tmp_path / "report.html"
    result = runner.invoke(
        cli.app,
        [
            "costs",
            "--start",
            "2026-01-01",
            "--end",
            "2026-02-01",
            "-p",
            "dev",
            "-p",
            "prod",
            "--view",
            "summary",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Total across 2 accounts: $40.00" in result.output
    assert "222222222222" in out.read_text()


def test_costs_skips_a_broken_profile_when_several(stubbed_cli):
    _costs(stubbed_cli, "dev")
    stubbed_cli.stub("ce", "old").add_client_error(
        "get_cost_and_usage", "AccessDeniedException", "no"
    )
    result = runner.invoke(
        cli.app, ["costs", "--start", "2026-01-01", "--end", "2026-02-01", "-p", "dev", "-p", "old"]
    )
    assert result.exit_code == 0, result.output
    assert "Skipped old" in result.output


def test_single_profile_error_is_short(stubbed_cli):
    stubbed_cli.stub("ce").add_client_error(
        "get_cost_and_usage", "AccessDeniedException", "User is not authorized"
    )
    result = runner.invoke(cli.app, ["costs", "--start", "2026-01-01", "--end", "2026-02-01"])
    assert result.exit_code == 1
    assert "AccessDeniedException" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["costs", "--start", "2026-02-01", "--end", "2026-01-01"],
        ["costs", "-o", "report.xlsx"],
    ],
)
def test_bad_input_exits_2(args):
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2


def test_services_json(stubbed_cli):
    stubbed_cli.stub("ce").add_response(
        "get_dimension_values",
        {
            "DimensionValues": [{"Value": "Amazon S3"}],
            "ReturnSize": 1,
            "TotalSize": 1,
        },
    )
    result = runner.invoke(
        cli.app, ["services", "--json", "--start", "2026-01-01", "--end", "2026-02-01"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == ["Amazon S3"]


def test_cost_category_without_first_seen(stubbed_cli, tmp_path):
    stubbed_cli.stub("ce").add_response(
        "get_cost_and_usage",
        {
            "ResultsByTime": [
                period("2026-01-01", "2026-02-01", [group(["Team$web", "Amazon S3"], "3")]),
            ]
        },
    )
    stubbed_cli.identity("1")
    out = tmp_path / "team.json"
    result = runner.invoke(
        cli.app,
        [
            "cost-category",
            "Team",
            "--no-first-seen",
            "--start",
            "2026-01-01",
            "--end",
            "2026-02-01",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["values"][0]["value"] == "web"


def test_rightsizing_rejects_unknown_type():
    result = runner.invoke(cli.app, ["optimize", "rightsizing", "--type", "gpu"])
    assert result.exit_code == 2


def test_rightsizing_html_is_not_supported(stubbed_cli, tmp_path):
    stubbed_cli.stub("compute-optimizer").add_response(
        "get_ec2_instance_recommendations", {"instanceRecommendations": []}
    )
    result = runner.invoke(
        cli.app,
        ["optimize", "rightsizing", "-t", "ec2", "-r", "us-east-1", "-o", str(tmp_path / "r.html")],
    )
    assert result.exit_code == 2
    assert "HTML is not available" in result.output


def test_hub(stubbed_cli):
    stubbed_cli.stub("cost-optimization-hub").add_response(
        "list_recommendations",
        {
            "items": [
                {
                    "resourceId": "i-1",
                    "currentResourceType": "Ec2Instance",
                    "estimatedMonthlySavings": 5.0,
                },
            ]
        },
    )
    result = runner.invoke(cli.app, ["optimize", "hub"])
    assert result.exit_code == 0, result.output
    assert "i-1" in result.output


def test_cache_list_and_clear(stubbed_cli):
    _costs(stubbed_cli)
    runner.invoke(cli.app, ["costs", "--start", "2026-01-01", "--end", "2026-02-01"])
    listed = runner.invoke(cli.app, ["cache", "list"])
    assert "1 entries" in listed.output
    cleared = runner.invoke(cli.app, ["cache", "clear"])
    assert "Removed 1" in cleared.output
    assert "Cache is empty" in runner.invoke(cli.app, ["cache", "list"]).output
