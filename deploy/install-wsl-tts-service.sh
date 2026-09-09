#!/usr/bin/env bash
# Install the imood TTS service under systemd inside WSL2 (Ubuntu-24.04).
# Run from WSL as root:
#   sudo bash /mnt/c/imood-backend/deploy/install-wsl-tts-service.sh
#
# Idempotent: re-run after editing imood-tts.service / imood-tts.env.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! systemctl is-system-running --quiet 2>/dev/null && \
   [ "$(ps -p 1 -o comm=)" != "systemd" ]; then
  echo "!! systemd is not PID 1 in this WSL distro."
  echo "   Add to /etc/wsl.conf:"
  echo "       [boot]"
  echo "       systemd=true"
  echo "   then 'wsl.exe --shutdown' from Windows and re-run this script."
  exit 1
fi

install -m 0644 "$SRC/imood-tts.service" /etc/systemd/system/imood-tts.service

# Don't clobber a local /etc/imood-tts.env that the operator has tuned.
if [ ! -f /etc/imood-tts.env ]; then
  install -m 0644 "$SRC/imood-tts.env" /etc/imood-tts.env
  echo "-> wrote /etc/imood-tts.env (defaults)"
else
  echo "-> kept existing /etc/imood-tts.env"
fi

touch /var/log/imood-tts.log

systemctl daemon-reload
systemctl enable imood-tts.service
systemctl restart imood-tts.service

echo
echo "installed + started. follow the boot log with:"
echo "    journalctl -u imood-tts -f      # or: tail -f /var/log/imood-tts.log"
echo "health (once warm, ~40s):"
echo "    curl -s localhost:8001/health"
