#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
  --set app_user="$POSTGRES_APP_USER" \
  --set app_password="$POSTGRES_APP_PASSWORD" <<'EOSQL'
CREATE ROLE factory_migration_owner NOLOGIN NOINHERIT;
GRANT factory_migration_owner TO CURRENT_USER;
GRANT USAGE, CREATE ON SCHEMA public TO factory_migration_owner;
CREATE ROLE :"app_user" LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_password';
EOSQL
