#!/usr/bin/env bash
# Server hardening for the Gaming Content Engine host (Ubuntu 24.04, e.g. Hetzner CX33).
#
# Run once as root on the server:   sudo ./infrastructure/server/harden.sh
# Preview without changes:          sudo ./infrastructure/server/harden.sh --dry-run
# Private operation (Cloudflare Tunnel, no open web ports):  add --tunnel
#
# What it does (idempotent):
#   1. automatic security updates (unattended-upgrades)
#   2. firewall: only SSH, HTTP and HTTPS reachable (ufw); with --tunnel only SSH
#   3. SSH: keys only, no password login, root only with a key
#   4. fail2ban against SSH brute force
#   5. Docker log rotation and no direct port publishing past the firewall rules
#
# Before running: make sure your SSH key login works, otherwise step 3 locks you out.
set -euo pipefail

DRY=0
TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --tunnel) TUNNEL=1 ;;
    *) echo "Unbekannte Option: $arg (erlaubt: --dry-run, --tunnel)" >&2; exit 2 ;;
  esac
done
SSH_PORT="${SSH_PORT:-22}"

run() {
  echo "+ $*"
  if [[ $DRY -eq 0 ]]; then "$@"; fi
}

write_file() {  # write_file PATH CONTENT
  echo "+ write $1"
  if [[ $DRY -eq 0 ]]; then printf '%s\n' "$2" > "$1"; fi
}

if [[ $DRY -eq 0 && $EUID -ne 0 ]]; then
  echo "Bitte als root ausführen (sudo)." >&2
  exit 1
fi

if [[ $DRY -eq 0 ]] && ! grep -qs "ssh-" /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; then
  echo "Kein SSH-Schlüssel hinterlegt – Abbruch, sonst sperrt Schritt 3 den Zugang." >&2
  exit 1
fi

echo "== 1. Automatische Sicherheitsupdates"
run apt-get update -q
run apt-get install -y -q unattended-upgrades ufw fail2ban
write_file /etc/apt/apt.conf.d/20auto-upgrades 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";'

echo "== 2. Firewall: nur SSH, HTTP, HTTPS"
run ufw default deny incoming
run ufw default allow outgoing
run ufw limit "${SSH_PORT}/tcp"
if [[ $TUNNEL -eq 1 ]]; then
  # Cloudflare Tunnel connects outbound; no inbound web ports needed.
  run ufw delete allow 80/tcp || true
  run ufw delete allow 443/tcp || true
else
  run ufw allow 80/tcp
  run ufw allow 443/tcp
fi
run ufw --force enable

echo "== 3. SSH nur mit Schlüssel"
write_file /etc/ssh/sshd_config.d/50-gce-hardening.conf "PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 3
X11Forwarding no"
run sshd -t
run systemctl reload ssh

echo "== 4. fail2ban für SSH"
write_file /etc/fail2ban/jail.d/gce-sshd.local "[sshd]
enabled = true
port = ${SSH_PORT}
maxretry = 5
bantime = 1h"
run systemctl enable --now fail2ban
run systemctl restart fail2ban

echo "== 5. Docker"
# All services except Caddy bind to 127.0.0.1 in docker-compose.yml, so the
# Docker port rules cannot open anything past ufw. Log rotation for the daemon:
if [[ ! -f /etc/docker/daemon.json ]]; then
  run mkdir -p /etc/docker
  write_file /etc/docker/daemon.json '{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "5"}, "live-restore": true}'
  echo "Docker neu starten, wenn gerade keine Produktion läuft: systemctl restart docker"
else
  echo "/etc/docker/daemon.json existiert bereits – unverändert gelassen."
fi

if [[ $TUNNEL -eq 1 ]]; then
  echo "Fertig. Zusätzlich empfohlen: Hetzner Cloud Firewall, eingehend nur 22 (am besten nur von deiner IP)."
else
  echo "Fertig. Zusätzlich empfohlen: Hetzner Cloud Firewall mit denselben Regeln (22, 80, 443)."
fi
