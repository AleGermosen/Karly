#!/usr/bin/env bash
#
# One-command deploy from THIS (dev) machine to the OptiPlex.
#
#   1. pushes the current branch to GitHub
#   2. SSHes to the target, pulls, updates deps, restarts the service
#   3. prints the service status
#
# Configure the target once (add to your ~/.bashrc):
#   export KARLY_HOST=karly-optiplex         # user@host or an SSH alias
#   export KARLY_REMOTE_DIR=Karly            # optional, defaults to "Karly"
#
# Usage:  ./deploy/deploy.sh
set -euo pipefail

HOST="${KARLY_HOST:?Set KARLY_HOST, e.g. export KARLY_HOST=karly-optiplex}"
REMOTE_DIR="${KARLY_REMOTE_DIR:-Karly}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "==> Pushing '$BRANCH' to origin..."
git push origin "$BRANCH"

echo "==> Deploying on $HOST:$REMOTE_DIR ..."
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
.venv/bin/pip install -q -r requirements.txt
# Both bots (German + English) run the same checkout, so any code change
# needs both units restarted — restarting only "karly" here would leave the
# English bot running stale code until someone noticed and restarted it by hand.
for u in karly karly-english; do
  systemctl --user restart "\$u"
done
sleep 2
for u in karly karly-english; do
  echo "== \$u =="
  systemctl --user --no-pager status "\$u" | head -n 15
done
REMOTE

echo "==> Done. Live logs:  make logs   (or ssh $HOST 'journalctl --user -u karly -u karly-english -f')"
