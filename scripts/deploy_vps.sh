#!/usr/bin/env bash
# scripts/deploy_vps.sh
#
# Idempotent deploy/redeploy script for a plain Ubuntu/Debian VPS
# (DigitalOcean or Hetzner both provision standard Ubuntu droplets/servers --
# no cloud-provider API integration needed here, just SSH access).
#
# Usage: ssh onto the VPS, clone this repo, `cd` into it, then run this
# script. Safe to re-run for redeploys (`git pull && ./scripts/deploy_vps.sh`).
#
# Prerequisites this script does NOT handle for you (see README.md's
# "Docker / VPS deployment" section for the exact steps):
#   - Pointing your domain's A record at this VPS's IP address.
#   - The first-ever TLS certificate bootstrap (chicken-and-egg: Nginx needs
#     to already be serving the ACME challenge before certbot can succeed,
#     so it's a documented two-phase manual process, not scripted here).
#   - Filling in .env with real secret values (this script refuses to run
#     without one -- see below).
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Install Docker + the Compose plugin if missing.
if ! command -v docker &> /dev/null; then
    echo "Docker not found -- installing via Docker's official convenience script..."
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable docker
systemctl start docker

# 2. .env must already exist and be filled in -- never run with blank secrets.
if [ ! -f .env ]; then
    echo "ERROR: .env not found." >&2
    echo "Copy .env.example to .env and fill in every value before running this script." >&2
    exit 1
fi

# 3. First-ever run: no certificate volume yet -- remind about the TLS
#    bootstrap steps rather than silently starting Nginx in a broken state.
if ! docker volume inspect "$(basename "$PWD")_certbot-etc" &> /dev/null; then
    echo "No existing certbot-etc volume found -- this looks like a first deploy."
    echo "See README.md's 'Docker / VPS deployment' section for the TLS bootstrap"
    echo "steps (issue the first certificate) before traffic can reach the app over HTTPS."
fi

# 4. Build and (re)start. restart: unless-stopped (docker-compose.yml) plus
#    the Docker daemon itself starting on boot (systemctl enable docker,
#    above) is the standard "survives crash and reboot" combination -- no
#    separate systemd unit wrapping docker compose is needed.
docker compose up -d --build

echo ""
echo "Deployed. Useful commands:"
echo "  docker compose ps"
echo "  docker compose logs -f app"
echo "  docker compose logs -f nginx"
