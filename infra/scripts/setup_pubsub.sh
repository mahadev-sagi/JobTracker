#!/usr/bin/env bash
# =============================================================================
# JobTracker — Google Cloud Pub/Sub & Gmail Watch Setup
#
# Automates the creation of a Pub/Sub topic and push subscription, grants
# Gmail publish permissions, and registers a Gmail watch so that new
# incoming emails trigger a push notification to the JobTracker webhook.
# =============================================================================
set -euo pipefail

# Colour helpers
if [[ -t 1 ]]; then
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; CYAN=''; NC=''
fi

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()    { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
step()    { echo -e "\n${CYAN}==> $*${NC}"; }

GCP_PROJECT="${GCP_PROJECT:-}"
PUBSUB_TOPIC="${PUBSUB_TOPIC:-jobtracker-gmail}"
PUBSUB_SUB="${PUBSUB_SUB:-jobtracker-gmail-push}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
GMAIL_USER_EMAIL="${GMAIL_USER_EMAIL:-}"

GMAIL_SERVICE_ACCOUNT="gmail-api-push@system.gserviceaccount.com"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)         GCP_PROJECT="$2";       shift 2;;
    --topic)           PUBSUB_TOPIC="$2";      shift 2;;
    --subscription)    PUBSUB_SUB="$2";        shift 2;;
    --webhook-url)     WEBHOOK_URL="$2";       shift 2;;
    --email)           GMAIL_USER_EMAIL="$2";  shift 2;;
    -h|--help)
      echo "Usage: $0 --project GCP_PROJECT --webhook-url WEBHOOK_URL --email GMAIL_EMAIL [options]"
      exit 0
      ;;
    *) fail "Unknown argument: $1";;
  esac
done

if ! command -v gcloud &>/dev/null; then
  fail "gcloud CLI is not installed. Please install the Google Cloud SDK."
fi

if [[ -z "$GCP_PROJECT" ]]; then
  fail "GCP project is required. Pass --project <id> or set GCP_PROJECT."
fi

if [[ -z "$WEBHOOK_URL" ]]; then
  fail "Webhook URL is required. Pass --webhook-url <url> or set WEBHOOK_URL."
fi

step "Setting GCP project to ${GCP_PROJECT}"
gcloud config set project "$GCP_PROJECT"

step "Creating Pub/Sub topic: ${PUBSUB_TOPIC}"
if gcloud pubsub topics describe "$PUBSUB_TOPIC" &>/dev/null; then
  info "Topic '${PUBSUB_TOPIC}' already exists."
else
  gcloud pubsub topics create "$PUBSUB_TOPIC"
  info "Topic '${PUBSUB_TOPIC}' created."
fi

step "Granting Gmail publish permissions on topic"
gcloud pubsub topics add-iam-policy-binding "$PUBSUB_TOPIC" \
  --member="serviceAccount:${GMAIL_SERVICE_ACCOUNT}" \
  --role="roles/pubsub.publisher"

step "Creating push subscription: ${PUBSUB_SUB}"
if gcloud pubsub subscriptions describe "$PUBSUB_SUB" &>/dev/null; then
  info "Subscription '${PUBSUB_SUB}' already exists. Updating push endpoint..."
  gcloud pubsub subscriptions update "$PUBSUB_SUB" --push-endpoint="$WEBHOOK_URL"
else
  gcloud pubsub subscriptions create "$PUBSUB_SUB" \
    --topic="$PUBSUB_TOPIC" \
    --push-endpoint="$WEBHOOK_URL" \
    --ack-deadline=30
  info "Subscription '${PUBSUB_SUB}' created with endpoint: ${WEBHOOK_URL}"
fi

info "Pub/Sub setup completed successfully!"
info "Topic: projects/${GCP_PROJECT}/topics/${PUBSUB_TOPIC}"
info "Subscription: projects/${GCP_PROJECT}/subscriptions/${PUBSUB_SUB}"
