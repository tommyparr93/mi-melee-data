-- Creates the read-only login the Ask Tom agent uses for SQL.
-- Must run as a superuser (postgres), connected to the target database:
--
--   psql -U postgres -d <db> -v agent_pw="..." -v app_owner=<app db user> -f create_agent_role.sql
--
-- Then run `python manage.py setup_agent_db` as the app user to create the views.
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE mimelee_agent LOGIN PASSWORD %L', :'agent_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mimelee_agent') \gexec
ALTER ROLE mimelee_agent WITH LOGIN PASSWORD :'agent_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 4;

-- Belt and braces: even if a query got past the app's SQL checker, the session
-- defaults are read-only, short-running and memory-capped.
ALTER ROLE mimelee_agent SET default_transaction_read_only = on;
ALTER ROLE mimelee_agent SET statement_timeout = '5s';
ALTER ROLE mimelee_agent SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE mimelee_agent SET work_mem = '16MB';
ALTER ROLE mimelee_agent SET search_path = agent;

SELECT format('GRANT CONNECT ON DATABASE %I TO mimelee_agent', current_database()) \gexec

-- PostgreSQL 14 lets every role create objects in `public` and make temp tables.
-- Remove that from PUBLIC (the PG15+ default) and give CREATE back to the app owner
-- explicitly so migrations keep working.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT CREATE ON SCHEMA public TO %I', :'app_owner') \gexec
SELECT format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT TEMPORARY ON DATABASE %I TO %I', current_database(), :'app_owner') \gexec

-- No direct access to any raw table or function-created object in public.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mimelee_agent;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM mimelee_agent;

-- The schema the views live in; the app owner creates the views and grants SELECT on them.
SELECT format('CREATE SCHEMA IF NOT EXISTS agent AUTHORIZATION %I', :'app_owner') \gexec

\echo 'mimelee_agent ready. Now run: python manage.py setup_agent_db'
