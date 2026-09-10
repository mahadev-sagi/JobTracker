#!/usr/bin/env bash
# =============================================================================
# JobTracker — Database Setup Script
#
# Creates the PostgreSQL database and user (if they don't already exist) and
# runs all migration files from backend/src/db/migrations/.
# =============================================================================
set -euo pipefail

# Colour helpers
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; NC=''
fi

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-jobtracker_admin}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-jobtracker}"
DB_SUPERUSER="${DB_SUPERUSER:-postgres}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)     DB_HOST="$2";     shift 2;;
    --port)     DB_PORT="$2";     shift 2;;
    --user)     DB_USER="$2";     shift 2;;
    --password) DB_PASSWORD="$2"; shift 2;;
    --dbname)   DB_NAME="$2";     shift 2;;
    --superuser) DB_SUPERUSER="$2"; shift 2;;
    -h|--help)
      echo "Usage: $0 [--host HOST] [--port PORT] [--user USER] [--password PW] [--dbname DB] [--superuser SU]"
      exit 0
      ;;
    *) fail "Unknown argument: $1";;
  esac
done

if ! command -v psql &>/dev/null; then
  fail "psql is not installed. Install PostgreSQL client tools first."
fi

if [[ -z "$DB_PASSWORD" ]]; then
  read -rsp "Enter password for database user '${DB_USER}': " DB_PASSWORD
  echo
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MIGRATIONS_DIR="${PROJECT_ROOT}/backend/src/db/migrations"

info "Configuration:"
info "  Host:       ${DB_HOST}:${DB_PORT}"
info "  Superuser:  ${DB_SUPERUSER}"
info "  App user:   ${DB_USER}"
info "  Database:   ${DB_NAME}"
info "  Migrations: ${MIGRATIONS_DIR}"
echo

psql_su() {
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_SUPERUSER" -d postgres \
    --no-psqlrc --set ON_ERROR_STOP=on "$@"
}

info "Checking if user '${DB_USER}' exists..."
USER_EXISTS=$(psql_su -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}';" 2>/dev/null || true)

if [[ "$USER_EXISTS" == "1" ]]; then
  info "User '${DB_USER}' already exists — skipping creation."
else
  info "Creating user '${DB_USER}'..."
  psql_su -c "CREATE USER \"${DB_USER}\" WITH PASSWORD '${DB_PASSWORD}' LOGIN;"
  info "User '${DB_USER}' created."
fi

info "Checking if database '${DB_NAME}' exists..."
DB_EXISTS=$(psql_su -tAc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}';" 2>/dev/null || true)

if [[ "$DB_EXISTS" == "1" ]]; then
  info "Database '${DB_NAME}' already exists — skipping creation."
else
  info "Creating database '${DB_NAME}'..."
  psql_su -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\" ENCODING 'UTF8';"
  info "Database '${DB_NAME}' created."
fi

info "Granting privileges on '${DB_NAME}' to '${DB_USER}'..."
psql_su -c "GRANT ALL PRIVILEGES ON DATABASE \"${DB_NAME}\" TO \"${DB_USER}\";"

if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  warn "Migrations directory not found at ${MIGRATIONS_DIR} — skipping migrations."
else
  MIGRATION_FILES=("${MIGRATIONS_DIR}"/*.sql)
  if [[ ${#MIGRATION_FILES[@]} -eq 0 || ! -e "${MIGRATION_FILES[0]}" ]]; then
    warn "No .sql migration files found in ${MIGRATIONS_DIR} — skipping."
  else
    info "Running ${#MIGRATION_FILES[@]} migration(s)..."
    export PGPASSWORD="$DB_PASSWORD"
    for migration in "${MIGRATION_FILES[@]}"; do
      filename="$(basename "$migration")"
      info "  Applying: ${filename}"
      psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --no-psqlrc --set ON_ERROR_STOP=on -f "$migration"
    done
    unset PGPASSWORD
    info "All migrations applied."
  fi
fi

info "Database setup complete!"
