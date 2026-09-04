"""Run Alembic migrations and reproducible synthetic seed data as an admin operation."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from industrial_ai_agent.infrastructure.persistence.demo_seed import seed_demo_data


def main() -> None:
    database_url = os.getenv("FACTORY_DATABASE_ADMIN_URL")
    if not database_url:
        raise RuntimeError("FACTORY_DATABASE_ADMIN_URL must be configured")
    config_path = Path.cwd() / "alembic.ini"
    if not config_path.is_file():
        raise RuntimeError(
            "alembic.ini must be available from the migration working directory"
        )
    config = Config(str(config_path))
    command.upgrade(config, "head")
    seed_demo_data(database_url)


if __name__ == "__main__":
    main()
