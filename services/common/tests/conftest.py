"""Shared pytest configuration for services/common.

Integration tests (marked ``@pytest.mark.integration``) require a real Postgres
reachable via the ``TEST_DATABASE_URL`` env var, with the pgvector extension
installable. When that var is unset, those tests are skipped — never faked.
"""
import os

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip_integration = pytest.mark.skip(
        reason="TEST_DATABASE_URL not set; skipping integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
