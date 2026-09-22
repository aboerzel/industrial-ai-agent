"""Regression coverage for model-assignment upgrades against a real PostgreSQL DB."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

ADMIN_DATABASE_URL = os.getenv("FACTORY_DATABASE_ADMIN_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL,
    reason="requires FACTORY_DATABASE_ADMIN_URL for isolated PostgreSQL migration coverage",
)


@pytest.fixture
def migrated_database() -> Iterator[Engine]:
    """Create an isolated database migrated exactly through revision 0021."""

    with _isolated_database("0021_agent_run_failure_origin") as engine:
        yield engine


@pytest.fixture
def fresh_database() -> Iterator[Engine]:
    """Create an empty isolated database for a direct-to-head install check."""

    with _isolated_database() as engine:
        yield engine


@contextmanager
def _isolated_database(revision: str | None = None) -> Iterator[Engine]:
    assert ADMIN_DATABASE_URL is not None
    database_name = f"pers01_upgrade_{uuid4().hex}"
    admin_url = make_url(ADMIN_DATABASE_URL)
    maintenance_url = admin_url.set(database="postgres")
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    migration_engine: Engine | None = None
    try:
        with maintenance_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        database_url = admin_url.set(database=database_name)
        setup_engine = create_engine(database_url)
        try:
            with setup_engine.begin() as connection:
                connection.execute(
                    text(
                        "GRANT USAGE, CREATE ON SCHEMA public "
                        "TO factory_migration_owner"
                    )
                )
        finally:
            setup_engine.dispose()
        if revision is not None:
            with _migration_database_url(
                database_url.render_as_string(hide_password=False)
            ):
                command.upgrade(_alembic_config(), revision)
        migration_engine = create_engine(database_url)
        yield migration_engine
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        with maintenance_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        maintenance_engine.dispose()


def test_upgrade_from_0021_preserves_existing_operator_assignments(
    migrated_database: Engine,
) -> None:
    expected = (
        ("agent", 0, "local_quality", "MANUAL", None, "operator:alice"),
        ("agent", 1, None, "AUTO", "COST_FIRST", "operator:dana"),
        ("agent", 2, "local_fast", "MANUAL", None, "operator:bob"),
        ("agent", 3, None, "AUTO", "QUALITY_FIRST", "operator:carol"),
        ("rca.reasoning", 0, "local_quality", "MANUAL", None, "operator:rca"),
        # There is no authoritative provenance at revision 0021.  This
        # default-looking historic row must be retained like every other row.
        ("vision.vlm", 0, "local_quality", "MANUAL", None, "legacy-bootstrap"),
    )
    _replace_assignments(migrated_database, expected)

    _upgrade_to_head(migrated_database)

    actual = _assignment_rows(migrated_database)
    for row in expected:
        assert row in actual
    assert len(actual) == len({(row[0], row[1]) for row in actual})
    assert len(actual) == 9


def test_upgrade_from_0021_creates_only_missing_current_defaults(
    migrated_database: Engine,
) -> None:
    _replace_assignments(migrated_database, ())

    _upgrade_to_head(migrated_database)

    actual = _assignment_rows(migrated_database)
    assert actual == tuple(
        (consumer_id, classification, "local_quality", "MANUAL", None, "migration:0022")
        for consumer_id in ("agent", "rca.reasoning")
        for classification in range(4)
    )


def test_fresh_install_has_current_default_assignments(
    fresh_database: Engine,
) -> None:
    _upgrade_to_head(fresh_database)

    actual = _assignment_rows(fresh_database)
    assert actual == tuple(
        (consumer_id, classification, "local_quality", "MANUAL", None, "migration:0022")
        for consumer_id in ("agent", "rca.reasoning")
        for classification in range(4)
    )


def _replace_assignments(
    engine: Engine,
    assignments: tuple[tuple[str, int, str | None, str, str | None, str], ...],
) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM agent_runtime.model_assignments"))
        for (
            consumer_id,
            classification,
            model_id,
            mode,
            policy,
            updated_by,
        ) in assignments:
            connection.execute(
                text(
                    """
                    INSERT INTO agent_runtime.model_assignments (
                        consumer_id, data_classification, model_id, selection_mode,
                        selection_policy, updated_by
                    ) VALUES (
                        :consumer_id, :classification, :model_id, :mode, :policy,
                        :updated_by
                    )
                    """
                ),
                {
                    "consumer_id": consumer_id,
                    "classification": classification,
                    "model_id": model_id,
                    "mode": mode,
                    "policy": policy,
                    "updated_by": updated_by,
                },
            )


def _upgrade_to_head(engine: Engine) -> None:
    with _migration_database_url(engine.url.render_as_string(hide_password=False)):
        command.upgrade(_alembic_config(), "head")


def _assignment_rows(
    engine: Engine,
) -> tuple[tuple[str, int, str | None, str, str | None, str | None], ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT consumer_id, data_classification, model_id, selection_mode,
                       selection_policy, updated_by
                FROM agent_runtime.model_assignments
                ORDER BY consumer_id, data_classification
                """
            )
        )
        return tuple(tuple(row) for row in rows)


def _alembic_config() -> Config:
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


@contextmanager
def _migration_database_url(database_url: str) -> Iterator[None]:
    previous = os.environ.get("FACTORY_DATABASE_ADMIN_URL")
    os.environ["FACTORY_DATABASE_ADMIN_URL"] = database_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FACTORY_DATABASE_ADMIN_URL", None)
        else:
            os.environ["FACTORY_DATABASE_ADMIN_URL"] = previous
