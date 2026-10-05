#!/usr/bin/env bash
# Bring the server up to date with the repository and the newest images.
# Run by cron every 5 minutes (see bootstrap.sh); safe to run by hand.
#
# Pull-based on purpose: the server needs no inbound SSH from GitHub and holds
# no deploy credentials. A push to main builds images; within minutes this
# picks them up. `docker compose up -d` only recreates containers whose image
# or configuration actually changed, so an idle run does nothing.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/../.." && pwd)"
cd "$DEPLOY_DIR"

# shellcheck disable=SC1091
set -a; source .env; set +a
BRANCH="${DEPLOY_BRANCH:-main}"

caddy_before="$(sha256sum Caddyfile)"
git -C "$REPO_DIR" fetch -q origin "$BRANCH"
git -C "$REPO_DIR" checkout -q "$BRANCH"
git -C "$REPO_DIR" merge -q --ff-only "origin/$BRANCH"

docker compose pull -q
docker compose up -d --remove-orphans

# A changed Caddyfile is a bind mount, so the container is not recreated;
# tell Caddy to re-read it.
if [ "$caddy_before" != "$(sha256sum Caddyfile)" ]; then
    docker compose exec -T web caddy reload --config /etc/caddy/Caddyfile
fi

# Old image layers otherwise fill a small disk within weeks.
docker image prune -f >/dev/null
