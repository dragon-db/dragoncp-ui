#!/usr/bin/env bash
#
# Bring the production instance up to the current checkout.
#
# Run this from your own shell, not from a service or a cron job: it needs npm
# on PATH (nvm is loaded by your interactive profile) and it ends in a sudo
# systemctl restart.
#
#   ./deploy.sh
#
# What it does, in order: snapshot the database, build the React app, run the
# test suite, restart the service, and check that the app answers. Any failing
# step aborts before the restart, so a bad build or a red suite never reaches
# production.
#
# The frontend build is a deploy step, deliberately not an ExecStartPre in the
# unit file. A restart must not depend on npm or on the network, and with
# Restart=always a build in the unit would turn a crash loop into a build loop.
# The unit only *checks* that frontend/dist/index.html exists.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Snapshots live beside the checkout rather than inside it, so nothing that
# cleans the working tree can reach them. Override on another machine with
# DRAGONCP_BACKUP_DIR.
BACKUP_DIR="${DRAGONCP_BACKUP_DIR:-$(dirname "$REPO_ROOT")/backups/dragoncp_prod}"
SERVICE="${DRAGONCP_SERVICE:-dragoncp-ui}"
PORT="${DRAGONCP_PORT:-5000}"
KEEP_SNAPSHOTS="${DRAGONCP_KEEP_SNAPSHOTS:-5}"

step() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

command -v npm >/dev/null || fail "npm is not on PATH (nvm not loaded? run this from your own shell)"
[[ -f dragoncp.db ]] || fail "dragoncp.db not found in $REPO_ROOT"

step "Snapshotting the database"
mkdir -p "$BACKUP_DIR"
SNAPSHOT="$BACKUP_DIR/dragoncp.db.pre_deploy_$(date +%Y%m%d_%H%M%S)"
# SQLite's own backup API, so the copy is consistent even though the service is
# still running and may be mid-write. `cp` can capture a torn page.
venv/bin/python - "$SNAPSHOT" <<'PY'
import sqlite3, sys
dst = sys.argv[1]
src = sqlite3.connect('file:dragoncp.db?mode=ro', uri=True)
out = sqlite3.connect(dst)
src.backup(out)
out.close(); src.close()
check = sqlite3.connect('file:%s?mode=ro' % dst, uri=True)
assert check.execute('pragma quick_check').fetchone()[0] == 'ok', 'snapshot failed quick_check'
print('  %s' % dst)
PY

# Prune only our own pre_deploy snapshots; hand-made milestone copies are left
# alone because they do not match this glob.
ls -1t "$BACKUP_DIR"/dragoncp.db.pre_deploy_* 2>/dev/null \
  | tail -n +$((KEEP_SNAPSHOTS + 1)) | xargs -r rm -v

step "Building the React app"
pushd frontend >/dev/null
if [[ ! -d node_modules || package-lock.json -nt node_modules ]]; then
  npm ci
fi
npm run build
popd >/dev/null
[[ -f frontend/dist/index.html ]] || fail "build finished without frontend/dist/index.html"

step "Running the test suite"
venv/bin/python -m pytest tests/ -q

step "Restarting $SERVICE"
sudo systemctl restart "$SERVICE"

step "Verifying"
# The service takes a moment to bind; poll rather than guess at a sleep.
for _ in $(seq 1 30); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "http://localhost:$PORT/" || true)"
  [[ "$code" == "200" ]] && break
  sleep 1
done
printf '  GET / -> %s\n' "$code"
[[ "$code" == "200" ]] || fail "app is not serving (503 means the build did not land)"
systemctl --no-pager --lines=0 status "$SERVICE"

printf '\n\033[1;32mDeploy complete.\033[0m\n'
