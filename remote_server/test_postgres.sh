#!/usr/bin/env bash
# Disposable local PostgreSQL verification. Never connects to a hosted database.
set -euo pipefail
: "${PG_BINDIR:?Set PG_BINDIR to an installed PostgreSQL bin directory}"
: "${PG_SHAREDIR:?Set PG_SHAREDIR to the installation share/postgresql directory}"
PORT="${GA_TEST_PG_PORT:-18734}"
[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT > 1024 && PORT < 65536 )) || exit 2
TMP=$(mktemp -d /tmp/game-assist-pg-XXXXXX)
chmod 700 "$TMP"
cleanup() {
  "$PG_BINDIR/pg_ctl" -D "$TMP/data" stop -m immediate >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
python - "$TMP/password" <<'PY'
import os, secrets, sys
fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
os.write(fd,secrets.token_hex(32).encode());os.close(fd)
PY
"$PG_BINDIR/initdb" -D "$TMP/data" -L "$PG_SHAREDIR" --locale=C --encoding=UTF8 \
  --auth-local=reject --auth-host=scram-sha-256 --pwfile="$TMP/password" >"$TMP/init.log" 2>&1
"$PG_BINDIR/pg_ctl" -D "$TMP/data" -l "$TMP/server.log" \
  -o "-c unix_socket_directories='' -c listen_addresses=127.0.0.1 -p $PORT -c jit=off" -w start >/dev/null
export GA_TEST_POSTGRES_URL="postgresql://$(id -un):$(cat "$TMP/password")@127.0.0.1:$PORT/postgres?sslmode=disable"
python -m unittest discover -s tests -q
