"""AWS sessions and clients.

Every AWS call in awsce goes through :class:`AwsContext`, so tests can swap in
stubbed clients and the CLI can query several profiles in one run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.config import Config

# Cost Explorer, Cost Optimization Hub and Organizations are global APIs
# served from us-east-1.
GLOBAL_REGION = "us-east-1"

_CLIENT_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

ClientFactory = Callable[[str | None, str, str | None], Any]


def _boto3_client(profile: str | None, service: str, region: str | None) -> Any:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client(service, region_name=region, config=_CLIENT_CONFIG)


@dataclass
class AwsContext:
    """Creates and reuses AWS clients per (profile, service, region)."""

    default_region: str | None = None
    factory: ClientFactory = _boto3_client
    _clients: dict[tuple[str | None, str, str | None], Any] = field(default_factory=dict)

    def client(self, service: str, profile: str | None = None, region: str | None = None) -> Any:
        key = (profile, service, region or self.default_region)
        if key not in self._clients:
            self._clients[key] = self.factory(profile, service, key[2])
        return self._clients[key]

    def ce(self, profile: str | None = None) -> Any:
        """Cost Explorer client."""
        return self.client("ce", profile, GLOBAL_REGION)

    def account_id(self, profile: str | None = None) -> str:
        """Return the account ID behind a profile, or "unknown"."""
        try:
            identity = self.client("sts", profile, GLOBAL_REGION).get_caller_identity()
        except Exception:  # identity is nice to have, not required
            return "unknown"
        return str(identity.get("Account", "unknown"))


def available_profiles() -> list[str]:
    """Profiles configured in ~/.aws/config and ~/.aws/credentials."""
    return sorted(boto3.Session().available_profiles)


def paginate(call: Callable[..., dict[str, Any]], token_key: str, **kwargs: Any) -> Iterator[dict]:
    """Yield every page of an AWS API that uses a next-token field.

    Cost Explorer uses ``NextPageToken``; Compute Optimizer and Cost
    Optimization Hub use ``nextToken``.
    """
    while True:
        page = call(**kwargs)
        yield page
        token = page.get(token_key)
        if not token:
            return
        kwargs[token_key] = token
