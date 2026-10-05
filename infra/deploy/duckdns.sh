#!/usr/bin/env bash
# Point DUCKDNS_SUBDOMAIN.duckdns.org at this server (cron, every 5 minutes).
#
# An EC2 instance without an Elastic IP gets a new public IP whenever it is
# stopped and started. Re-registering frequently keeps the hostname, and so
# the HTTPS certificate and Google's OAuth redirect, working across that.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
set -a; source "$DEPLOY_DIR/.env"; set +a

if [ -z "${DUCKDNS_SUBDOMAIN:-}" ] || [ -z "${DUCKDNS_TOKEN:-}" ]; then
    exit 0
fi

# An empty ip= tells DuckDNS to use the address the request came from.
result="$(curl -fsS --max-time 30 \
    "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=")"
if [ "$result" != "OK" ]; then
    echo "DuckDNS update failed: $result" >&2
    exit 1
fi
