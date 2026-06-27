#!/usr/bin/env bash
#
# Manual deploy for Fan the Flames. No GitHub Actions.
#
# Usage:
#   ./deploy.sh <ssh-host> [install-dir]
#
# Examples:
#   ./deploy.sh lightsail /srv/fan-the-flames   # AWS Lightsail (public, port 23)
#   ./deploy.sh pi /opt/fan-the-flames          # Raspberry Pi
#
# Requires on this machine: ssh (host configured), rsync.
# Requires on the host: python3 with venv, passwordless sudo, systemd.
set -euo pipefail

HOST="${1:?usage: deploy.sh <ssh-host> [install-dir]}"
DIR="${2:-/srv/fan-the-flames}"
UNIT="fan-the-flames.service"

echo ">> Deploying to ${HOST}:${DIR}"

# 1. Ensure the install dir exists and is owned by the login user (so rsync
#    needs no sudo). DynamicUser only needs read access to world-readable files.
ssh "$HOST" "sudo mkdir -p '$DIR' && sudo chown \"\$(id -un):\$(id -gn)\" '$DIR'"

# 2. Sync runtime files.
rsync -az telnet_server.py requirements.txt "$HOST:$DIR/"

# 3. Render the unit for this install dir and install it.
sed "s#/srv/fan-the-flames#${DIR}#g" "$UNIT" > "/tmp/${UNIT}.rendered"
scp "/tmp/${UNIT}.rendered" "$HOST:/tmp/${UNIT}"
rm -f "/tmp/${UNIT}.rendered"
ssh "$HOST" "sudo install -m 644 /tmp/${UNIT} /etc/systemd/system/${UNIT} && rm /tmp/${UNIT}"

# 4. Build/refresh the venv.
ssh "$HOST" "cd '$DIR' && python3 -m venv venv && ./venv/bin/pip install --quiet --upgrade pip && ./venv/bin/pip install --quiet -r requirements.txt"

# 5. Enable + restart, then verify.
ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable --now ${UNIT} && sudo systemctl restart ${UNIT} && sleep 3 && systemctl is-active ${UNIT} && if ss -ltn | grep -Eq ':23 '; then echo 'listening on :23'; else echo 'ERROR: not listening on :23' >&2; exit 1; fi"

echo ">> Done."
