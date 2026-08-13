#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$SERVICE_DIR"

sed "s#__CONCLAVE_PROJECT_ROOT__#$PROJECT_ROOT#g" "$SCRIPT_DIR/conclave.service" > "$SERVICE_DIR/conclave.service"

systemctl --user daemon-reload
systemctl --user enable --now conclave.service
echo "User-Service eingerichtet: conclave.service"
