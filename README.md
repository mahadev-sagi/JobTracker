# JobTracker

Personal job application tracker: React dashboard, FastAPI API, PostgreSQL,
a job-listing scraper, and an optional Gmail classification pipeline.

## Personal deployment on this PC

Requires Docker Desktop running and Docker Compose 2.24.4 or newer.
Copy `.env.example` to `.env` only if you do not already have `.env`.
Keep the existing database password when reusing the existing database volume.

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --build
```

Open http://localhost:5173. This serves a compiled frontend through nginx.
The backend runs from its image, with one worker because scraper progress is
currently held in memory. Source changes require rebuilding with the command above.
All published ports bind to this PC's loopback interface. The dashboard has no
login and is intended for local use. Remote dashboard access still requires
an authenticated private access layer.

- Dashboard: http://localhost:5173
- API documentation: http://localhost:8000/docs
- Webhook gateway: http://localhost:8080
- Database: localhost on `POSTGRES_HOST_PORT` (5432 by default)

Data remains in the existing `pgdata` Docker volume across rebuilds. Do not run
`docker compose down -v` unless you intend to delete that database.
Containers restart when Docker starts; the PC and Docker must stay running.

## Gmail setup (not yet connected)

1. Create a Google Cloud project and enable Gmail API and Pub/Sub.
2. Configure OAuth consent and a Desktop app OAuth client. Download its
   `credentials.json`, add your account as a test user if appropriate, and run:

   ```powershell
   backend/.venv/Scripts/python.exe backend/scripts/bootstrap_gmail_token.py --credentials credentials.json --output backend/secrets/token.json
   ```

3. Set these in `.env`: `GOOGLE_CLOUD_PROJECT_ID`, `GMAIL_USER_EMAIL`,
   `GOOGLE_CREDENTIALS_JSON=/app/secrets/token.json`, and `LLM_API_KEY`.
   `LLM_BASE_URL` and `LLM_MODEL` select an OpenAI-compatible classifier.
4. Create the `GOOGLE_PUBSUB_TOPIC` topic. Grant
   `gmail-api-push@system.gserviceaccount.com` the Pub/Sub Publisher role on it.
5. Expose **only the webhook gateway on port 8080** through your tunnel.
   Example for a temporary test: `cloudflared tunnel --url http://localhost:8080`.
   Never point the public tunnel at 8000 or 5173.
6. Create an authenticated Pub/Sub push subscription to
   `https://YOUR-TUNNEL/api/webhooks/gmail`. Configure an OIDC service account
   and audience. Set matching `PUBSUB_AUDIENCE` and
   `PUBSUB_SERVICE_ACCOUNT_EMAIL` in `.env`.
   The shared-secret mode is for manual testing; use OIDC for Google pushes.
7. Re-run the deployment command to load the updated environment, then call:

   ```powershell
   Invoke-RestMethod -Method Post http://localhost:8000/api/webhooks/gmail/watch
   ```

8. Arrange daily watch renewal, and verify a real incoming application email.
   Watch renewal automation and a permanent tunnel are not configured yet.

Webhook requests fail closed without authentication. Gmail, LLM, and database
failures return 503 for retry; a failed batch does not advance its sync cursor.
A temporary tunnel is only a test endpoint; configure a stable endpoint for
ongoing use. Gmail OAuth consent and the real-email test require your account.

References: [Gmail push setup](https://developers.google.com/workspace/gmail/api/guides/push)
and [Pub/Sub push authentication and retries](https://docs.cloud.google.com/pubsub/docs/push).

## Development

```powershell
docker compose up -d --build
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe -m ruff check backend/src backend/tests
cd frontend
npm.cmd run lint
npm.cmd run build
```

Development uses Vite and source mounts. After backend source edits, restart
its container; after environment edits, recreate it with `up -d`.

## API and code map

| Route | Purpose |
|---|---|
| `GET /health` | Process liveness |
| `GET, POST /api/applications/` | List/filter/page or create applications |
| `GET, PATCH, DELETE /api/applications/{id}` | Read, update, or soft-delete |
| `GET /api/applications/stats/summary` | Dashboard totals |
| `POST /api/scraper/run` | Trigger ingestion |
| `GET /api/scraper/status` | In-memory progress; resets on restart |
| `POST /api/webhooks/gmail` | Authenticated Pub/Sub push |
| `POST /api/webhooks/gmail/test` | Local manual classification test |
| `POST /api/webhooks/gmail/watch` | Local watch registration/renewal |

`backend/src` contains the API, asyncpg database access, scraper, and email
pipeline. `frontend/src` contains the React dashboard. Schema migrations live
in `backend/src/db/migrations`; these are SQL files, not Alembic migrations.
Postgres applies them automatically only when creating a fresh volume.

The AWS Terraform and Lambda files under `infra/aws` are unfinished scaffolding,
not a functioning cloud deployment. See `HANDOFF.md` for current limitations.
