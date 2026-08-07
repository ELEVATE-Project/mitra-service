#!/bin/sh
set -e

PGBOUNCER_LISTEN_PORT=6432
PGBOUNCER_INI_DIR="${PGBOUNCER_INI_DIR:-/etc/pgbouncer}"
PGBOUNCER_INI="${PGBOUNCER_INI_DIR}/pgbouncer.ini"
PGBOUNCER_TEMPLATE="$(pwd)/infra/pgbouncer.ini.template"
PGBOUNCER_USERLIST="${PGBOUNCER_INI_DIR}/userlist.txt"

mkdir -p "${PGBOUNCER_INI_DIR}" /var/log/pgbouncer /var/run/pgbouncer
# sudo chown -R "$(whoami)" /etc/pgbouncer /var/log/pgbouncer /var/run/pgbouncer

sed \
  -e "s|<DATABASE_HOST>|${DATABASE_HOST}|g" \
  -e "s|<DATABASE_PORT>|${DATABASE_PORT:-5432}|g" \
  -e "s|<DATABASE_NAME>|${DATABASE_NAME}|g" \
  -e "s|^server_tls_sslmode = .*|server_tls_sslmode = ${PG_SSL_MODE:-require}|" \
  -e "s|^server_tls_ca_file = .*|server_tls_ca_file = ${PG_SSL_ROOT_CERT:-/etc/ssl/certs/rds_certificate.pem}|" \
  -e "s|^auth_file = .*|auth_file = ${PGBOUNCER_USERLIST}|" \
  "$PGBOUNCER_TEMPLATE" > "$PGBOUNCER_INI"

# Store the plaintext password: pgbouncer hashes it on the fly for client md5
# auth, but still needs the plaintext to complete a SCRAM handshake with the
# upstream Postgres server. A pre-hashed md5 entry can't do that and fails
# with "server login failed: wrong password type".
gen_userlist_entry() {
  user="$1"
  password="$2"
  printf '"%s" "%s"\n' "$user" "$password"
}

gen_userlist_entry "${DATABASE_USER}" "${DATABASE_PASSWORD}" > "$PGBOUNCER_USERLIST"

pgbouncer "$PGBOUNCER_INI" &

for i in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p "${PGBOUNCER_LISTEN_PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Point the app at the local pooler; upstream host/port already consumed above.
export DATABASE_HOST=127.0.0.1
export DATABASE_PORT="${PGBOUNCER_LISTEN_PORT}"

# cron self-daemonizes; drives /etc/cron.daily/logrotate, which rotates
# /etc/logrotate.d/pgbouncer
cron

exec "$@"
