#!/usr/bin/env python3
"""Create dedicated AutoTramita databases on the existing postgres container."""
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

def sql(statement):
    r = subprocess.run(['docker', 'exec', '-i', 'postgres', 'psql', '-X', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-Atq'], input=statement + '\n', text=True, capture_output=True)
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

for prefix, expected in [('APP', f'autotramita_{env}'), ('KEYCLOAK', f'autotramita_keycloak_{env}')]:
    db, user, password = (values.get(prefix + '_DB_' + key, '') for key in ('NAME', 'USER', 'PASSWORD'))
    if db != expected or user != expected:
        sys.exit(f'{prefix} database and user must both be {expected}')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,}', password):
        sys.exit(f'{prefix}_DB_PASSWORD must be at least 32 URL-safe characters')
    role_exists = sql(f"SELECT 1 FROM pg_roles WHERE rolname = '{user}';") == '1'
    owner = sql(f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '{db}';")
    if owner and owner != user:
        sys.exit(f'{db} already exists with a different owner; no changes made to it.')
    if not role_exists:
        sql(f"CREATE ROLE \"{user}\" LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;")
    if sql(f"SELECT 1 FROM pg_roles WHERE rolname = '{user}' AND rolcanlogin AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls);") != '1':
        sys.exit(f'{user} has unsafe role attributes; correct them manually before continuing.')
    if not owner:
        sql(f'CREATE DATABASE "{db}" OWNER "{user}";')
    sql(f'REVOKE CONNECT ON DATABASE "{db}" FROM PUBLIC; GRANT CONNECT ON DATABASE "{db}" TO "{user}";')
    check_login(user, db, password)
    print(f'{db}: owner and credentials verified')
