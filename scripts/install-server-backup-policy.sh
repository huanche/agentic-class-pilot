#!/usr/bin/env bash
set -euo pipefail
SOURCE="${1:-$(dirname "$0")/server-backup-policy.py}"
sudo -n install -d -m 755 /usr/local/lib/agentic-class-pilot
sudo -n install -o root -g root -m 755 "$SOURCE" /usr/local/lib/agentic-class-pilot/server-backup-policy.py
sudo -n tee /etc/systemd/system/agentic-backup-retention.service >/dev/null <<'EOF'
[Unit]
Description=Keep two verified local production backups

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/agentic-class-pilot/server-backup-policy.py apply
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=20min
EOF
sudo -n tee /etc/systemd/system/agentic-backup-retention.timer >/dev/null <<'EOF'
[Unit]
Description=Hourly production backup retention

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=120
Unit=agentic-backup-retention.service

[Install]
WantedBy=timers.target
EOF
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now agentic-backup-retention.timer
