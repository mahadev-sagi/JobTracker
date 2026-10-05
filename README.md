# JobTracker

Multi-user job application tracker: a React dashboard, FastAPI API,
PostgreSQL, a shared job-listing scraper, and optional per-user Gmail
classification that updates application statuses from recruiter email.

Users sign in with Google. Access is invite-only (`ALLOWED_EMAILS`). Scraped
listings are shared; each user's applications, Gmail connection and email
history are private to them.

## Running locally

Requires Docker Desktop and Docker Compose 2.24.4 or newer. Copy
`.env.example` to `.env` if you do not already have one.

```powershell
docker compose up -d --build                                               # development (Vite, source mounts)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # compiled frontend via nginx
```

Open http://localhost:5173. Without a Google OAuth client, set
`DEV_LOGIN_ENABLED=true` (development only) to sign in as any address.

Schema migrations in `backend/src/db/migrations` are applied by the backend at
startup and recorded in `schema_migrations`; there is no manual step.

Data lives in the `pgdata` Docker volume. `docker compose down -v` deletes it.
`infra/scripts/backup-db.ps1` writes a verified `pg_dump` archive to `backups/`.

### Upgrading a pre-multi-user database

Migration `003_multi_user.sql` moves scraped rows into the shared `listings`
table and keeps the old table as `legacy_applications`. After signing in once,
claim the old applications for your account:

```powershell
docker compose exec backend python -m scripts.claim_legacy_data you@gmail.com
```

## Google setup

One Google Cloud project serves every user.

1. Enable the **Gmail API** and **Pub/Sub**.
2. OAuth consent screen: External, publishing status **Testing**. Add each
   invited user as a test user (limit 100). Testing mode avoids Google's
   verification for the restricted `gmail.readonly` scope.
3. Create an OAuth client of type **Web application** with redirect URIs
   `{PUBLIC_URL}/api/auth/callback` and `{PUBLIC_URL}/api/gmail/callback`.
   Set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
4. Generate `TOKEN_ENCRYPTION_KEY` (command in `.env.example`).
5. Create the `GOOGLE_PUBSUB_TOPIC` topic and grant
   `gmail-api-push@system.gserviceaccount.com` the Pub/Sub Publisher role on it.
   Set `GOOGLE_CLOUD_PROJECT_ID`.
6. Create a **push** subscription to `{PUBLIC_URL}/api/webhooks/gmail` with
   authentication enabled (OIDC service account and audience). Set the
   acknowledgement deadline to 600 seconds and a retry policy with a minimum
   backoff of about 10 seconds. Set `PUBSUB_AUDIENCE` and
   `PUBSUB_SERVICE_ACCOUNT_EMAIL` to match.

Users then connect their own inbox from **Settings → Connect Gmail**. The
backend renews each Gmail watch before its 7-day expiry, and scrapes listings
every `SCRAPER_INTERVAL_HOURS`, from an in-process scheduler.

Email processing: the webhook syncs one mailbox at a time (a second delivery
for the same mailbox gets 503 and is retried), never moves the history cursor
backwards, and falls back to a date-based inbox scan when Gmail has expired
the stored history. An email that could refer to several applications at one
company changes nothing and is listed as "Needs you" in Settings.

## Development

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe -m ruff check backend/src backend/tests backend/scripts
cd frontend; npm.cmd run lint; npm.cmd run build
```

API and email tests need a disposable database; they are skipped without it.
Its schema is wiped on each run.

```powershell
$env:TEST_DATABASE_URL = "postgresql://jobtracker:PASSWORD@127.0.0.1:5433/jobtracker_test"
```

Use `127.0.0.1`, not `localhost`: on Windows the IPv6 attempt adds ~2 s per
connection. State-changing API calls require the header
`X-Requested-With: XMLHttpRequest` (CSRF guard); the frontend sends it.

## API

| Route | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /api/auth/login`, `/callback` | Google sign-in |
| `GET /api/auth/me`, `POST /api/auth/logout` | Current user, sign out |
| `GET, POST /api/applications/` | The user's applications |
| `GET, PATCH, DELETE /api/applications/{id}` | Read, update, soft-delete |
| `GET /api/applications/stats/summary` | Dashboard totals |
| `GET /api/listings/` | Shared listings not yet applied to |
| `POST /api/listings/{id}/apply` | Create an application from a listing |
| `GET /api/gmail/connect`, `/callback` | Connect Gmail |
| `DELETE /api/gmail` | Disconnect and revoke |
| `GET /api/gmail/activity` | Recent emails acted on |
| `POST /api/gmail/test` | Classify pasted email text (dry run by default) |
| `POST /api/webhooks/gmail` | Pub/Sub push (bearer-authenticated) |
| `POST /api/scraper/run` | Admin: scrape now |
| `GET /api/scraper/status` | Last scraper run |

The AWS Terraform and Lambda files under `infra/aws` predate this design and
are not used. See `HANDOFF.md` for status and next steps.
