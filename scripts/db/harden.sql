-- Schema hardening for the application database (ADR-002, G5-01).
-- Run as a superuser connected to the target database. Placeholders in braces are
-- validated, quoted identifiers filled in by app.core.dbroles.harden().
-- Table grants for the platform role and the append-only audit table are decided per migration.
REVOKE ALL ON DATABASE {db} FROM PUBLIC;
GRANT CONNECT ON DATABASE {db} TO {owner}, {app}, {worker}, {platform};
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO {owner};
GRANT USAGE ON SCHEMA public TO {app}, {worker}, {platform};
-- Migration state lives in its own schema; runtime roles get no access to it.
CREATE SCHEMA IF NOT EXISTS schema_migrations AUTHORIZATION {owner};
REVOKE ALL ON SCHEMA schema_migrations FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}, {worker};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {app}, {worker};
