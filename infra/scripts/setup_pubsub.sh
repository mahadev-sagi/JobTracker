#!/usr/bin/env bash
# Run in Google Cloud Shell. Gmail watches are registered per user by the app.
set -euo pipefail
GCP_PROJECT="${GCP_PROJECT:-}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
PUBSUB_TOPIC="${PUBSUB_TOPIC:-gmail-notifications}"
PUBSUB_SUB="${PUBSUB_SUB:-jobtracker-gmail-push}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project|--webhook-url|--topic|--subscription)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "Missing value for $1" >&2; exit 1; }
            case "$1" in
                --project) GCP_PROJECT="$2";;
                --webhook-url) WEBHOOK_URL="$2";;
                --topic) PUBSUB_TOPIC="$2";;
                --subscription) PUBSUB_SUB="$2";;
            esac
            shift 2;;
        -h|--help) echo "Usage: bash $0 --project PROJECT_ID --webhook-url https://DOMAIN/api/webhooks/gmail [--topic NAME] [--subscription NAME]"; exit 0;;
        *) echo "Unknown argument: $1" >&2; exit 1;;
    esac
done
command -v gcloud >/dev/null || { echo 'Run this in Google Cloud Shell.' >&2; exit 1; }
[[ -n "$GCP_PROJECT" && "$WEBHOOK_URL" == https://* ]] || { echo 'Project ID and HTTPS webhook URL required.' >&2; exit 1; }
gcloud services enable gmail.googleapis.com pubsub.googleapis.com iam.googleapis.com --project="$GCP_PROJECT"
project_number="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')"
[[ "$project_number" =~ ^[0-9]+$ ]] || { echo 'Could not determine project number.' >&2; exit 1; }
gcloud beta services identity create --service=pubsub.googleapis.com --project="$GCP_PROJECT"
push_account="jobtracker-pubsub-push@${GCP_PROJECT}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$push_account" --project="$GCP_PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create jobtracker-pubsub-push --display-name='JobTracker Gmail push' --project="$GCP_PROJECT"
fi
# Grant signing permission on this account only.
gcloud iam service-accounts add-iam-policy-binding "$push_account" \
    --member="serviceAccount:service-${project_number}@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role=roles/iam.serviceAccountTokenCreator --project="$GCP_PROJECT" >/dev/null
if ! gcloud pubsub topics describe "$PUBSUB_TOPIC" --project="$GCP_PROJECT" >/dev/null 2>&1; then
    gcloud pubsub topics create "$PUBSUB_TOPIC" --project="$GCP_PROJECT"
fi
gcloud pubsub topics add-iam-policy-binding "$PUBSUB_TOPIC" \
    --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
    --role=roles/pubsub.publisher --project="$GCP_PROJECT" >/dev/null
push_flags=(--project="$GCP_PROJECT" --push-endpoint="$WEBHOOK_URL"
    --push-auth-service-account="$push_account" --push-auth-token-audience="$WEBHOOK_URL"
    --ack-deadline=600 --min-retry-delay=10s --max-retry-delay=600s)
if gcloud pubsub subscriptions describe "$PUBSUB_SUB" --project="$GCP_PROJECT" >/dev/null 2>&1; then
    existing_topic="$(gcloud pubsub subscriptions describe "$PUBSUB_SUB" --project="$GCP_PROJECT" --format='value(topic)')"
    [[ "$existing_topic" == "projects/$GCP_PROJECT/topics/$PUBSUB_TOPIC" ]] || { echo 'Existing subscription uses another topic. Choose another name.' >&2; exit 1; }
    gcloud pubsub subscriptions update "$PUBSUB_SUB" "${push_flags[@]}"
else
    gcloud pubsub subscriptions create "$PUBSUB_SUB" --topic="$PUBSUB_TOPIC" "${push_flags[@]}"
fi
gcloud pubsub subscriptions describe "$PUBSUB_SUB" --project="$GCP_PROJECT" --format='yaml(topic,pushConfig,ackDeadlineSeconds,retryPolicy)'
printf '\nPub/Sub setup complete. Server settings (not secrets):\n'
printf 'GOOGLE_CLOUD_PROJECT_ID=%s\nGOOGLE_PUBSUB_TOPIC=%s\nPUBSUB_AUDIENCE=%s\nPUBSUB_SERVICE_ACCOUNT_EMAIL=%s\n' "$GCP_PROJECT" "$PUBSUB_TOPIC" "$WEBHOOK_URL" "$push_account"
