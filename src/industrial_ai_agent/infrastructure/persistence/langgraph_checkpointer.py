"""Lifecycle for LangGraph's official PostgreSQL async checkpointer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


@asynccontextmanager
async def open_langgraph_postgres_checkpointer(
    database_url: str,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open and idempotently initialise the framework-owned checkpoint tables.

    The dedicated schema prevents the framework tables from being confused with
    application-owned `agent_runtime.agent_runs` records.  RLS is deliberately not
    attached to third-party checkpoint tables because it would alter framework queries.
    """
    if not database_url.strip():
        raise ValueError("database_url must not be empty")
    connection_string = _checkpoint_connection_string(database_url)
    async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:
        await checkpointer.setup()
        yield checkpointer


def _checkpoint_connection_string(database_url: str) -> str:
    """Pass a PostgreSQL `search_path` without interpolating SQL."""
    if database_url.startswith("postgresql+psycopg://"):
        database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    separator = "&" if "?" in database_url else "?"
    return f"{database_url}{separator}options={quote('-csearch_path=langgraph_checkpoint')}"
