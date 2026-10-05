#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server for JobTracker.
#
#   sudo git clone https://github.com/mahadev-sagi/JobTracker.git /opt/jobtracker
#   sudo bash /opt/jobtracker/infra/deploy/bootstrap.sh
#
# Installs Docker, adds swap, creates infra/deploy/.env with generated
# secrets, and installs the cron jobs for updates, backups and DuckDNS.
# Safe to re-run: every step checks before acting, and an existing .env is
# never overwritten.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/../.." && pwd)"

echo "==> Docker"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> Swap"
# 1 GB of RAM is enough to run the stack but not to absorb a spike (a large
# scrape, pulling images). Swap turns an out-of-memory kill into a slowdown.
if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -q vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-jobtracker.conf
fi

echo "==> Security updates"
apt-get install -y -qq unattended-upgrades >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Settings"
ENV_FILE="$DEPLOY_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$DEPLOY_DIR/.env.example" "$ENV_FILE"
    db_password="$(openssl rand -hex 24)"
    # A Fernet key is 32 random bytes, URL-safe base64 encoded.
    fernet_key="$(openssl rand -base64 32 | tr '+/' '-_')"
    sed -i "s|^POSTGRES_PASSWORD=__GENERATED__|POSTGRES_PASSWORD=$db_password|" "$ENV_FILE"
    sed -i "s|^TOKEN_ENCRYPTION_KEY=__GENERATED__|TOKEN_ENCRYPTION_KEY=$fernet_key|" "$ENV_FILE"
    echo "    Created $ENV_FILE with a generated database password and encryption key."
fi
chmod 600 "$ENV_FILE"
chmod +x "$DEPLOY_DIR"/*.sh

echo "==> Scheduled jobs"
cat > /etc/cron.d/jobtracker <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root $DEPLOY_DIR/duckdns.sh >> /var/log/jobtracker-duckdns.log 2>&1
*/5 * * * * root flock -n /run/jobtracker-update.lock $DEPLOY_DIR/update.sh >> /var/log/jobtracker-update.log 2>&1
30 3 * * * root $DEPLOY_DIR/backup.sh >> /var/log/jobtracker-backup.log 2>&1
CRON
cat > /etc/logrotate.d/jobtracker <<'ROTATE'
/var/log/jobtracker-*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
ROTATE

git config --global --add safe.directory "$REPO_DIR"

cat <<NEXT

Setup complete. Next:
  1. Edit $ENV_FILE: at least DOMAIN, DUCKDNS_SUBDOMAIN, DUCKDNS_TOKEN,
     ADMIN_EMAILS and LLM_API_KEY. Google settings can come later.
  2. Point DNS at this server:   $DEPLOY_DIR/duckdns.sh
  3. Start JobTracker:          cd $DEPLOY_DIR && docker compose up -d
  4. Watch it come up:          docker compose logs -f

After that, cron keeps it updated from GitHub every 5 minutes and backs up
the database nightly to the directory in BACKUP_DIR.
NEXT
