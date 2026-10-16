"""Test helpers: real boto3 clients with botocore Stubber, so no AWS calls are made."""

from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from botocore.stub import Stubber

from awsce.aws import AwsContext


class StubbedAws:
    """Hands out stubbed clients and keeps their Stubbers for setting responses."""

    def __init__(self) -> None:
        self.stubbers: dict[tuple[str | None, str], Stubber] = {}

    def stub(self, service: str, profile: str | None = None) -> Stubber:
        key = (profile, service)
        if key not in self.stubbers:
            client = boto3.client(
                service,
                region_name="us-east-1",
                aws_access_key_id="testing",
                aws_secret_access_key="testing",
            )
            stubber = Stubber(client)
            stubber.activate()
            self.stubbers[key] = stubber
        return self.stubbers[key]

    def factory(self, profile: str | None, service: str, region: str | None):
        return self.stub(service, profile).client

    def context(self) -> AwsContext:
        return AwsContext(factory=self.factory)

    def identity(self, account: str, profile: str | None = None) -> None:
        self.stub("sts", profile).add_response(
            "get_caller_identity",
            {"Account": account, "Arn": f"arn:aws:iam::{account}:user/test", "UserId": "AIDTEST"},
        )

    def assert_done(self) -> None:
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


@pytest.fixture
def aws() -> Iterator[StubbedAws]:
    stubbed = StubbedAws()
    yield stubbed
    stubbed.assert_done()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch) -> None:
    """Keep the cache and AWS config away from the developer's real files."""
    monkeypatch.setenv("AWSCE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))
    for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def group(keys: list[str], cost: str, quantity: str = "0", unit: str = "Hrs") -> dict:
    return {
        "Keys": keys,
        "Metrics": {
            "UnblendedCost": {"Amount": cost, "Unit": "USD"},
            "UsageQuantity": {"Amount": quantity, "Unit": unit},
        },
    }


def period(start: str, end: str, groups: list[dict]) -> dict:
    return {"TimePeriod": {"Start": start, "End": end}, "Groups": groups, "Estimated": False}
