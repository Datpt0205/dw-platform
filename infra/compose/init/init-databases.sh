#!/usr/bin/env bash
# Runs once on first postgres init: extra databases + platform roles.
# The runtime role (dw_app) is deliberately NOT a superuser and has no
# BYPASSRLS — RLS must apply to application queries.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Maintenance role: owns schema, runs migrations/seeds (may bypass RLS).
    CREATE ROLE dw_migrator LOGIN PASSWORD '${DW_DB_MIGRATOR_PASSWORD}' NOSUPERUSER BYPASSRLS CREATEDB;
    -- Runtime role: RLS ALWAYS applies.
    CREATE ROLE dw_app LOGIN PASSWORD '${DW_DB_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
    -- The signal analyst's role: it runs SQL a model wrote, so it holds no
    -- privilege at all until migration 0054 grants SELECT on three curated
    -- views. No base table, no write verb, no bypass. Roles are cluster
    -- objects and dw_migrator has no CREATEROLE, so a migration cannot make
    -- this one; scripts/create_agent_role.py does the same job for a cluster
    -- that was already initialised.
    CREATE ROLE dw_agent_ro LOGIN PASSWORD '${DW_DB_AGENT_RO_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    -- Provisioning authority (ADR-002): BYPASSRLS so it can create/list every
    -- tenant, but migration 0067 grants it ONLY the platform provisioning
    -- tables - no business schema - so it still cannot read tenant data. For a
    -- cluster initialised before this role, scripts/create_provisioner_role.py.
    CREATE ROLE dw_provisioner LOGIN PASSWORD '${DW_DB_PROVISIONER_PASSWORD}' NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;
    -- postgres-exporter's role (runtime-hardening R8.4): statistics through
    -- pg_monitor, no table, no bypass. The same attributes as
    -- scripts/create_monitor_role.py, which a cluster initialised before it uses.
    CREATE ROLE dw_monitor LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '${DW_DB_MONITOR_PASSWORD:?DW_DB_MONITOR_PASSWORD is required}';
    GRANT pg_monitor TO dw_monitor;

    CREATE DATABASE dw OWNER dw_migrator;
    CREATE DATABASE keycloak OWNER "$POSTGRES_USER";
    CREATE DATABASE langfuse OWNER "$POSTGRES_USER";

    GRANT CONNECT ON DATABASE dw TO dw_app;
    GRANT CONNECT ON DATABASE dw TO dw_agent_ro;
    GRANT CONNECT ON DATABASE dw TO dw_provisioner;
    GRANT CONNECT ON DATABASE dw TO dw_monitor;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname dw <<-EOSQL
    GRANT USAGE ON SCHEMA public TO dw_app;
EOSQL
