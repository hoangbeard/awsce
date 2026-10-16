import pytest

from awsce import optimize


def _option(instance_type, savings, pct):
    return {
        "instanceType": instance_type,
        "savingsOpportunity": {
            "savingsOpportunityPercentage": pct,
            "estimatedMonthlySavings": {"currency": "USD", "value": savings},
        },
    }


def test_best_option_keeps_config_and_savings_together():
    # Regression: the old code took the config from the first option but the
    # savings from the best one.
    option, savings, pct, currency = optimize.best_option(
        [_option("t3.large", 5.0, 10.0), _option("t3.small", 20.0, 40.0)]
    )
    assert option["instanceType"] == "t3.small"
    assert (savings, pct, currency) == (20.0, 40.0, "USD")


def test_best_option_empty():
    assert optimize.best_option([]) == ({}, 0.0, 0.0, "USD")


def _ec2(arn, name, current, options):
    return {
        "instanceArn": arn,
        "instanceName": name,
        "accountId": "111111111111",
        "currentInstanceType": current,
        "finding": "OVER_PROVISIONED",
        "recommendationOptions": options,
    }


def test_rightsizing_paginates_dedupes_and_sorts(aws):
    co = aws.stub("compute-optimizer")
    arn_a = "arn:aws:ec2:us-east-1:111111111111:instance/i-a"
    arn_b = "arn:aws:ec2:us-east-1:111111111111:instance/i-b"
    co.add_response(
        "get_ec2_instance_recommendations",
        {
            "instanceRecommendations": [
                _ec2(arn_a, "web", "m5.xlarge", [_option("m5.large", 30.0, 50.0)])
            ],
            "nextToken": "n",
        },
        {},
    )
    co.add_response(
        "get_ec2_instance_recommendations",
        {
            "instanceRecommendations": [
                _ec2(arn_b, "", "t3.large", [_option("t3.medium", 60.0, 50.0)]),
                _ec2(arn_a, "web", "m5.xlarge", [_option("m5.large", 30.0, 50.0)]),
            ],
        },
        {"nextToken": "n"},
    )

    result = optimize.rightsizing(aws.context(), [None], ["us-east-1"], ["ec2"])

    recs = result["recommendations"]
    assert result["errors"] == []
    assert [r["resource_id"] for r in recs] == ["i-b", "web"]
    assert recs[0]["recommended_config"] == "t3.medium"
    assert recs[0]["current_monthly_cost"] == pytest.approx(120.0)
    assert recs[0]["recommended_monthly_cost"] == pytest.approx(60.0)


def test_rightsizing_collects_errors_per_type(aws):
    co = aws.stub("compute-optimizer", "dev")
    co.add_client_error(
        "get_lambda_function_recommendations", "OptInRequiredException", "not opted in"
    )
    co.add_response(
        "get_ebs_volume_recommendations",
        {
            "volumeRecommendations": [
                {
                    "volumeArn": "arn:aws:ec2:us-east-1:1:volume/vol-1",
                    "accountId": "1",
                    "finding": "NotOptimized",
                    "currentConfiguration": {"volumeType": "gp2", "volumeSize": 100},
                    "volumeRecommendationOptions": [
                        {
                            "configuration": {"volumeType": "gp3", "volumeSize": 100},
                            "savingsOpportunity": {
                                "savingsOpportunityPercentage": 20.0,
                                "estimatedMonthlySavings": {"currency": "USD", "value": 2.0},
                            },
                        }
                    ],
                }
            ]
        },
    )

    result = optimize.rightsizing(aws.context(), ["dev"], ["us-east-1"], ["lambda", "ebs"])

    assert len(result["errors"]) == 1
    assert "dev/us-east-1/lambda" in result["errors"][0]
    rec = result["recommendations"][0]
    assert (rec["resource_id"], rec["current_config"], rec["recommended_config"]) == (
        "vol-1",
        "gp2 100 GiB",
        "gp3 100 GiB",
    )


def test_rightsizing_organization_queries_one_account_per_request(aws):
    co = aws.stub("compute-optimizer")
    co.add_response(
        "get_rds_database_recommendations", {"rdsDBRecommendations": []}, {"accountIds": ["1"]}
    )
    co.add_response(
        "get_rds_database_recommendations", {"rdsDBRecommendations": []}, {"accountIds": ["2"]}
    )
    result = optimize.rightsizing(aws.context(), [None], ["us-east-1"], ["rds"], ["1", "2"])
    assert result == {"recommendations": [], "errors": []}


def test_org_accounts_only_active(aws):
    aws.stub("organizations").add_response(
        "list_accounts",
        {
            "Accounts": [
                {"Id": "111111111111", "Name": "prod", "Status": "ACTIVE"},
                {"Id": "222222222222", "Name": "old", "Status": "SUSPENDED"},
            ]
        },
    )
    assert optimize.org_accounts(aws.context(), None) == {"111111111111": "prod"}


def test_hub_recommendations_maps_fields_and_limits(aws):
    hub = aws.stub("cost-optimization-hub", "dev")
    item = {
        "recommendationId": "r1",
        "accountId": "1",
        "region": "us-east-1",
        "resourceId": "i-1",
        "resourceArn": "arn:aws:ec2:us-east-1:1:instance/i-1",
        "currentResourceType": "Ec2Instance",
        "actionType": "Rightsize",
        "estimatedMonthlySavings": 12.5,
        "estimatedSavingsPercentage": 25.0,
        "currencyCode": "USD",
        "implementationEffort": "Low",
        "restartNeeded": True,
    }
    hub.add_response(
        "list_recommendations",
        {"items": [item, {**item, "recommendationId": "r2"}], "nextToken": "more"},
    )

    items = optimize.hub_recommendations(aws.context(), "dev", ["Ec2Instance"], limit=2)

    assert len(items) == 2
    first = items[0]
    assert first["resource_type"] == "Ec2Instance"
    assert first["monthly_savings"] == 12.5
    assert first["profile"] == "dev"
    assert first["rollback_possible"] is None
