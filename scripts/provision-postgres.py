#!/usr/bin/env python3
"""Create dedicated AutoTramita databases and roles on the existing postgres container.

Application database: four roles (owner, app, worker, platform) per ADR-002 and the G5 review.
Only the owner role owns objects and runs migrations; the others never own tables and have no BYPASSRLS.
Keycloak database: one owner role (Keycloak manages its own schema; no tenant RLS).
"""
import re
import subprocess
import sys
from pathlib import Path

if len(sys.argv) != 2 or sys.argv[1] not in ('prod', 'dev'):
    sys.exit('Usage: scripts/provision-postgres.py prod|dev')
env = sys.argv[1]
path = Path(__file__).resolve().parents[1] / '.secrets' / f'{env}.env'
if not path.is_file() or path.stat().st_mode & 0o077:
    sys.exit(f'{path}: create a root-only environment file first (chmod 600).')
values = {}
for line in path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#'):
        key, sep, value = line.partition('=')
        if not sep:
            sys.exit(f'Invalid environment line in {path}')
        values[key] = value
if values.get('ENVIRONMENT') != env:
    sys.exit('ENVIRONMENT does not match requested environment')

def sql(statement, db='postgres'):
    r = subprocess.run(['docker', 'exec', '-i', 'postgres', 'psql', '-X', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1', '-Atq'], input=statement + '\n', text=True, capture_output=True)
    if r.returncode:
        sys.exit('PostgreSQL operation failed: ' + r.stderr.strip())
    return r.stdout.strip()

def check_login(user, db, password):
    ip = subprocess.run(['docker', 'inspect', '-f', '{{(index .NetworkSettings.Networks "backend").IPAddress}}', 'postgres'], text=True, capture_output=True, check=True).stdout.strip()
    if not ip:
        sys.exit('The postgres container has no backend network address.')
    cmd = ['docker', 'exec', '-i', 'postgres', 'sh', '-c', 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -h "$3" -U "$1" -d "$2" -Atqc "SELECT 1"', 'sh', user, db, ip]
    r = subprocess.run(cmd, input=password + '\n', text=True, capture_output=True)
    if r.returncode or r.stdout.strip() != '1':
        sys.exit(f'Could not verify credentials for {user}/{db}; existing credentials were not changed.')

def read_role(prefix, expected_user):
    user, password = (values.get(prefix + key, '') for key in ('_USER', '_PASSWORD'))
    if user != expected_user:
        sys.exit(f'{prefix}_USER must be {expected_user}')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,}', password):
        sys.exit(f'{prefix}_PASSWORD must be at least 32 URL-safe characters')
    return user, password

def ensure_role(user, password):
    if sql(f"SELECT 1 FROM pg_roles WHERE rolname = '{user}';") != '1':
        sql(f"CREATE ROLE \"{user}\" LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;")
    if sql(f"SELECT 1 FROM pg_roles WHERE rolname = '{user}' AND rolcanlogin AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls);") != '1':
        sys.exit(f'{user} has unsafe role attributes; correct them manually before continuing.')

def ensure_db(db, owner):
    current = sql(f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '{db}';")
    if current and current != owner:
        sys.exit(f'{db} already exists with a different owner; no changes made to it.')
    if not current:
        sql(f'CREATE DATABASE "{db}" OWNER "{owner}";')

# Keycloak: single owner role.
kc_db = values.get('KEYCLOAK_DB_NAME', '')
kc_expected = f'autotramita_keycloak_{env}'
if kc_db != kc_expected:
    sys.exit(f'KEYCLOAK_DB_NAME must be {kc_expected}')
kc_user, kc_password = read_role('KEYCLOAK_DB', kc_expected)
ensure_role(kc_user, kc_password)
ensure_db(kc_db, kc_user)
sql(f'REVOKE CONNECT ON DATABASE "{kc_db}" FROM PUBLIC; GRANT CONNECT ON DATABASE "{kc_db}" TO "{kc_user}";')
check_login(kc_user, kc_db, kc_password)
print(f'{kc_db}: owner and credentials verified')

# Application database: owner / app / worker / platform.
app_db = values.get('APP_DB_NAME', '')
base = f'autotramita_{env}'
if app_db != base:
    sys.exit(f'APP_DB_NAME must be {base}')
roles = {name: read_role(f'APP_DB_{name.upper()}', f'{base}_{name}') for name in ('owner', 'app', 'worker', 'platform')}
if len({pw for _, pw in roles.values()}) != 4:
    sys.exit('The four application database roles must use distinct passwords')
for user, password in roles.values():
    ensure_role(user, password)
owner = roles['owner'][0]
runtime = [roles[name][0] for name in ('app', 'worker', 'platform')]
ensure_db(app_db, owner)
sql(f'REVOKE CONNECT ON DATABASE "{app_db}" FROM PUBLIC;')
for user, _ in roles.values():
    sql(f'GRANT CONNECT ON DATABASE "{app_db}" TO "{user}";')
# Schema hardening inside the application database. Table-level grants for the
# platform role and the append-only audit table are decided per migration.
q = lambda users: ', '.join(f'"{u}"' for u in users)
sql(f"""
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO "{owner}";
GRANT USAGE ON SCHEMA public TO {q(runtime)};
ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{roles['app'][0]}", "{roles['worker'][0]}";
ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{roles['app'][0]}", "{roles['worker'][0]}";
""", db=app_db)
for user, password in roles.values():
    check_login(user, app_db, password)
print(f'{app_db}: four roles (owner, app, worker, platform) and credentials verified')
