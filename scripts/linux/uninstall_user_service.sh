#!/usr/bin/env sh
set -eu

systemctl --user disable --now conclave.service || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/conclave.service"
systemctl --user daemon-reload
echo "User-Service entfernt: conclave.service"
