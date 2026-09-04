#!/bin/sh
set -eu

# Local single-instance demo lifecycle: migration and deterministic seed must finish
# before the read-only application role starts serving MCP requests.
python -m industrial_ai_agent.infrastructure.persistence.migrate
unset FACTORY_DATABASE_ADMIN_URL

exec "$@"
