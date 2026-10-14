"""Real database regressions, run only in the configured disposable test database."""

import asyncio
import logging
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_ADMIN_URL"),
    reason="requires explicitly configured integration database",
)


def test_embedded_migration_does_not_disable_application_failure_logging():
    loggers = [
        logging.getLogger(name)
        for name in (
            "industrial_ai_agent.api.failure_diagnostics",
            "industrial_ai_agent.application.rca_reasoning",
        )
    ]
    for logger in loggers:
        logger.disabled = False
    command.upgrade(Config("alembic.ini"), "head")
    assert all(not logger.disabled for logger in loggers)


def test_concurrent_investigation_appends_allocate_distinct_sequences():
    factory = PostgreSqlSessionFactory(os.environ["FACTORY_DATABASE_URL"])
    context = SecurityContext(
        "synthetic-integration", ("test",), DataClassification.CONFIDENTIAL, True
    )
    store = PostgreSqlAgentRunStore(factory, context)

    async def verify():
        first = await store.create(uuid4())
        created = await asyncio.gather(
            *(
                store.create(uuid4(), investigation_id=first.investigation_id)
                for _ in range(4)
            )
        )
        assert sorted(record.investigation_sequence for record in created) == [
            2,
            3,
            4,
            5,
        ]

    try:
        asyncio.run(verify())
    finally:
        factory.dispose()


def test_hidden_later_sequence_fails_closed_without_database_error():
    factory = PostgreSqlSessionFactory(os.environ["FACTORY_DATABASE_URL"])
    restricted = PostgreSqlAgentRunStore(
        factory,
        SecurityContext(
            "restricted-test", ("test",), DataClassification.RESTRICTED, True
        ),
    )
    public = PostgreSqlAgentRunStore(
        factory,
        SecurityContext("public-test", ("test",), DataClassification.PUBLIC, True),
    )

    async def verify():
        first = await restricted.create(
            uuid4(), data_classification=DataClassification.PUBLIC
        )
        await restricted.create(
            uuid4(),
            investigation_id=first.investigation_id,
            data_classification=DataClassification.RESTRICTED,
        )
        with pytest.raises(LookupError, match="context is unavailable"):
            await public.create(
                uuid4(),
                investigation_id=first.investigation_id,
                data_classification=DataClassification.PUBLIC,
            )
        assert len(await restricted.list_investigation(first.investigation_id)) == 2

    try:
        asyncio.run(verify())
    finally:
        factory.dispose()
