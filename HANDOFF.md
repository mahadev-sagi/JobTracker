# Deployment update - 2026-10-07

This update supersedes deployment status below.

- Owner confirmed AWS Free plan with $100 credits; SSH and DuckDNS work.
  Zero-spend budget alert is not yet confirmed.
- Server: `18.219.198.190`, Ubuntu **26.04 LTS** (not 24.04), x86_64,
  approximately 1 GB RAM and 20 GiB disk. SSH key stays on the owner's PC.
- Repository cloned to `/opt/jobtracker`; bootstrap completed: Docker,
  2 GiB swap, generated secrets, automatic security updates, and cron.
- Live: https://mahadev-jobs.duckdns.org. HTTPS certificate validates;
  HTTP redirects to HTTPS; frontend loads; backend and database healthy.
- Initial scrape imported 15,159 listings. Manual `update.sh` succeeded.
  First database backup created and archive listing verified by `backup.sh`.
- Server settings: `ADMIN_EMAILS` and `ACME_EMAIL` use
  `madhsa1972@gmail.com`; `ALLOWED_EMAILS` includes `scholar.mahadev@gmail.com`.
- Google project is `jobtracker-510921`. Replacement Web OAuth credentials
  were read from the owner's downloaded JSON and installed on the server
  without displaying secrets. Both redirect URIs match the live domain.
  Live auth config now reports `google=true`, `dev_login=false`; backend healthy.
  Owner confirmed Google sign-in opens the dashboard. Google test-user settings
  and API enablement have not been independently verified.
  Authenticated Pub/Sub push was subsequently provisioned successfully on
  2026-10-08 (see update below); server `PUBSUB_*` settings remain outstanding.
- `DUCKDNS_TOKEN` and `LLM_API_KEY` remain blank. DNS currently works from
  the owner's manual DuckDNS setup, but automatic IP updates need the token.
  Enter secrets directly on the server, never in chat.
- Copy encryption key and database backups somewhere off the server.
- Google Testing mode Gmail refresh tokens expire after **7 days**;
  scheduled watch renewal cannot prevent this. Plan for reconnecting during
  testing. Source: https://developers.google.com/identity/protocols/oauth2
- Gmail callback supports connecting a different Google mailbox to the
  signed-in app user. Thus the admin can connect `scholar.mahadev@gmail.com`
  by selecting it during Gmail consent; emails update that app user's board.
  Signing in as scholar instead creates a separate board. The earlier chat
  statement that sign-in must match the mailbox was too restrictive.
- Updated local `infra/scripts/setup_pubsub.sh` to enable APIs, provision the
  push service account and scoped signing grant, grant Gmail publication,
  and create/update authenticated push with 600 s ack and retry settings.
  Bash syntax checked on Ubuntu successfully. Not run against Google Cloud
  yet; owner must run in Cloud Shell.
- Still outstanding: run Pub/Sub setup, choose classifier privacy settings,
  and perform real Gmail/email-update and second-user isolation tests.

## Resume here: Gmail notifications

### Progress on 2026-10-08 (new machine)

- Owner ran `setup_pubsub.sh` successfully in Google Cloud Shell for
  `jobtracker-510921` and shared its output.
- Created the Pub/Sub service identity, `jobtracker-pubsub-push` service
  account, `gmail-notifications` topic, and `jobtracker-gmail-push`
  subscription; IAM grants completed successfully.
- Output confirms authenticated push to the live Gmail webhook, matching
  audience and service account, 600-second acknowledgement deadline, and
  retry backoff of 10–600 seconds.
- Resume at **step 6 below**: install the four settings on EC2 and recreate
  the backend. Owner explicitly confirmed the EC2 configuration step has
  **not been done yet**. Real Gmail delivery is not yet tested. Classifier
  configuration remains outstanding.
- On this Mac the repository is at `/Users/mahadev/JobTracker`. The owner
  can run the EC2 commands in AWS Console → EC2 → Instances → select the
  JobTracker instance → Connect → EC2 Instance Connect (username `ubuntu`),
  or through SSH with their key. Google Cloud Shell is a different machine;
  do not edit the server `.env` there. The Windows SSH path below refers to
  the previous PC; a Mac key path has not been confirmed.

1. Open https://console.cloud.google.com/?project=jobtracker-510921.
2. Click **Activate Cloud Shell** (`>_`) near the top right and wait for
   the terminal. Use Cloud Shell, not the EC2 SSH terminal.
3. In the Cloud Shell terminal's **three-dot menu**, choose **Upload** and
   upload the updated file from this PC:
   `C:\Users\ThisPC\JobTracker\infra\scripts\setup_pubsub.sh`.
   On another computer, first clone/pull this repository to get the file.
4. Run:

   ```bash
   bash ~/setup_pubsub.sh --project jobtracker-510921 --webhook-url https://mahadev-jobs.duckdns.org/api/webhooks/gmail
   ```

5. Authorize Cloud Shell if prompted. Save the final output or any error.
   The final output contains configuration values, not secrets. If Google
   requires billing, stop and review the zero-cost requirement before
   enabling billing.
6. After successful setup, configure the server's `.env` with:

   ```dotenv
   GOOGLE_CLOUD_PROJECT_ID=jobtracker-510921
   GOOGLE_PUBSUB_TOPIC=gmail-notifications
   PUBSUB_AUDIENCE=https://mahadev-jobs.duckdns.org/api/webhooks/gmail
   PUBSUB_SERVICE_ACCOUNT_EMAIL=jobtracker-pubsub-push@jobtracker-510921.iam.gserviceaccount.com
   ```

   Then apply settings on EC2:

   ```bash
   cd /opt/jobtracker/infra/deploy
   sudo docker compose up -d backend
   ```

7. Choose an email classifier provider/privacy policy and enter its key
   directly in the server `.env`; `LLM_API_KEY` is currently blank. Confirm
   the provider's current model name and set `LLM_MODEL`/`LLM_BASE_URL` as
   needed. Recreate the backend after changing settings.
8. Sign in as `madhsa1972@gmail.com`, add a test application, then use
   **Settings > Connect Gmail** and select `scholar.mahadev@gmail.com`.
   Ensure both addresses are Google OAuth test users. Confirm notifications
   are active, send a fake rejection matching the test application, and
   verify its status and recent email activity. If the mailbox is connected
   while signed in as scholar, the application must be on scholar's board.
9. Enter `DUCKDNS_TOKEN` directly on the server and run
   `sudo /opt/jobtracker/infra/deploy/duckdns.sh`. Save the encryption key
   and database backup off-server, confirm the AWS budget alert, and test
   second-user isolation before inviting friends.

SSH from this PC (never paste the key contents into chat):

```powershell
ssh -i C:\Users\ThisPC\Downloads\jobtracker.pem ubuntu@18.219.198.190
```

The OAuth client secret was replaced after being shared in chat. The new
credentials are already installed on EC2. No credentials belong in Git.
Changes to `.env` require `docker compose up -d`, not just `restart`.

# Previous handoff - 2026-10-04 (`main`, pushed)

This section supersedes everything below it.

## Direction

The owner wants JobTracker hosted, usable from any computer, by invited
friends (under 100), at zero cost. Decisions made:

- Hosting: a single small AWS EC2 instance running this Docker Compose stack
  (Postgres in a container, not RDS), on an AWS **Free plan** account so it
  can never be billed beyond the sign-up credits. The old AWS Terraform/Lambda
  design has been deleted.
- Domain: a free subdomain (DuckDNS), HTTPS via Caddy. Fallback: GitHub
  Student Pack domain if Google rejects the DuckDNS redirect URI.
- Access: Google sign-in, invite list in `ALLOWED_EMAILS`, Google OAuth app
  left in **Testing** mode (100 test users) to avoid paid verification of the
  restricted Gmail scope.

## Done (on `main`, not yet deployed)

- Multi-user schema (`003_multi_user.sql`): users, sessions, shared
  `listings`, per-user `applications`, per-user `gmail_accounts` with
  Fernet-encrypted refresh tokens, `processed_emails` with outcomes,
  `scraper_runs`.
- Migration runner applies migrations at startup (`src/db/migrate.py`);
  the Postgres initdb mount and `setup_db.sh` are gone.
- Google sign-in, server-side sessions, CSRF header guard, admin role,
  dev sign-in for local use.
- Per-user Gmail connect/disconnect via web OAuth; desktop bootstrap script
  removed.
- Email pipeline rewritten (`email_pipeline/processing.py`): per-mailbox
  advisory lock, cursor never moves backwards, expired-history recovery by
  date, revoked grants marked instead of retried forever, company names
  normalised, company-only matching refuses to guess between several open
  applications.
- Fixed: nested multipart emails returned an empty body (most real mail).
- In-process scheduler renews Gmail watches and scrapes daily.
- Frontend: sign-in page, Settings (Gmail + email activity), per-user queue.
- 93 backend tests pass, the API and pipeline ones against real Postgres. CI
  now starts a Postgres service. Frontend lint/build pass.
- Verified in a browser against a migrated copy of the real database: sign
  in, board, queue, apply, sign out, second user isolation, uninvited user
  refused. No real Google OAuth, Gmail or LLM call has been made.

**Local PC caution:** the four running containers are still the old
single-user build. The dev `backend` container bind-mounts the source, so
restarting it (or `docker compose up`) runs the new code and migrates the
local database to the multi-user schema. A pre-migration backup is in
`backups/` (2026-10-04); the only non-scraped rows are demo data. The
`jobtracker-webhook-gateway` container is no longer defined anywhere and can
be stopped.

## Deployment files (done)

`infra/deploy/`: production compose (Postgres, backend, Caddy web image),
Caddyfile, `bootstrap.sh` (Ubuntu 24.04: Docker, swap, generated secrets,
cron), `update.sh` (pull-based deploys every 5 min), `backup.sh` (nightly,
verified, 14 kept, optional S3), `duckdns.sh`. `.github/workflows/deploy.yml`
builds images to GHCR after CI passes on `main`. Removed: `infra/aws`, the
webhook gateway, `docker-compose.prod.yml`, the nginx frontend stage.

Verified locally with production images and DOMAIN=localhost: HTTP to HTTPS
redirect, SPA routes, security headers, API docs not exposed, CSRF guard,
1 MB body limit, webhook fails closed, migrations and first scrape on a fresh
database, backup rotation and a successful restore; ~145 MB memory total.
Not yet run on a real Ubuntu server: `bootstrap.sh`, `update.sh`, cron,
DuckDNS, Let's Encrypt.

On GitHub (2026-10-04): CI green on `main` (including the real-Postgres
tests), and the Build images workflow pushed `ghcr.io/mahadev-sagi/
jobtracker-backend` and `jobtracker-web`. Both pull anonymously (verified),
so the server needs no registry login.

## Next steps

Full detail for steps 1 to 4 is in `infra/deploy/README.md`; Google setup is
in `README.md`. Never paste keys, tokens or the `.pem` file into chat.

### 1. AWS account (owner)

- [ ] Create the account and choose the **Free plan**, not the paid plan.
      New accounts get about $100–200 of credits for 6 months; a free-plan
      account is never charged beyond them. Check the current terms on the
      sign-up page.
- [ ] Billing and Cost Management → Budgets → **zero spend** budget with an
      email alert. Billing → Credits shows what is left.

### 2. Launch the server (owner)

EC2 → Launch instance:

- [ ] Image: **Ubuntu Server 24.04 LTS**, 64-bit x86
- [ ] Type: **`t3.micro`** (or whatever is marked *Free tier eligible*; must
      be x86, the images are not built for ARM)
- [ ] Key pair: create one and keep the `.pem` file safe
- [ ] Network: SSH from **My IP only**; HTTP and HTTPS from anywhere
- [ ] Storage: **20 GiB gp3** (at most 30)
- [ ] Note the public IPv4 address

Expected use: about $13 a month of credits (instance, public IPv4, disk),
roughly $80 over 6 months.

### 3. DuckDNS (owner)

- [ ] Sign in at duckdns.org, claim a subdomain, note the token. Both go
      only into the server's `.env`.

### 4. Set up the server (owner, with help)

```powershell
ssh -i path\to\key.pem ubuntu@PUBLIC_IP
```

```bash
sudo git clone https://github.com/mahadev-sagi/JobTracker.git /opt/jobtracker
sudo bash /opt/jobtracker/infra/deploy/bootstrap.sh
sudo nano /opt/jobtracker/infra/deploy/.env
```

- [ ] In `.env` set `DOMAIN` (`name.duckdns.org`), `ACME_EMAIL`,
      `DUCKDNS_SUBDOMAIN`, `DUCKDNS_TOKEN`, `ADMIN_EMAILS` (own Google
      address), and `LLM_API_KEY`. The database password and encryption key
      are already generated.
- [ ] `sudo /opt/jobtracker/infra/deploy/duckdns.sh`
- [ ] `cd /opt/jobtracker/infra/deploy && sudo docker compose up -d`
- [ ] `https://DOMAIN` loads with a valid certificate; the first scrape
      fills the queue within a couple of minutes.
- [ ] Save a copy of `TOKEN_ENCRYPTION_KEY` somewhere safe off the server.

The sign-in page will say sign-in is not configured until step 5.

### 5. Google setup (next working session)

- [ ] Confirm the Google Cloud project exists; enable Gmail API and Pub/Sub.
- [ ] OAuth consent screen: External, **Testing**; add each invitee as a
      test user (max 100).
- [ ] OAuth client (Web application) with redirect URIs
      `https://DOMAIN/api/auth/callback` and `https://DOMAIN/api/gmail/callback`.
      If Google rejects the duckdns.org domain, fall back to a GitHub Student
      Pack domain.
- [ ] Pub/Sub topic, publisher grant for
      `gmail-api-push@system.gserviceaccount.com`, authenticated push
      subscription to `https://DOMAIN/api/webhooks/gmail` (600 s ack
      deadline, ~10 s minimum retry backoff).
- [ ] Fill the Google values and `PUBSUB_*` into `.env`;
      `sudo docker compose up -d`.
- [ ] `infra/scripts/setup_pubsub.sh` predates the multi-user design and
      still references `GMAIL_USER_EMAIL`; update or delete it.

### 6. Live test (owner, together)

- [ ] Sign in with Google; add an application by hand.
- [ ] Settings → Connect Gmail; confirm "notifications active".
- [ ] Send a fake rejection email for that company and role to the
      connected inbox; the card should move to Rejected and appear under
      Settings → Recent email activity.
- [ ] Invite one friend (`ALLOWED_EMAILS` plus Google test user) and confirm
      they see an empty board and the full queue.

### Known gaps

- Some scraped listings fail validation (a field exceeds its length) and are
  skipped.
- The backend image is ~480 MB (google-api-python-client, pytest in runtime
  requirements).
- The Gemini free tier may use submitted content to improve Google's
  products, which matters once friends' email goes through it; consider a
  paid tier or another provider before inviting others.
- `bootstrap.sh`, `update.sh`, cron, DuckDNS and Let's Encrypt are untested
  until the real server exists.

---

# Historical handoff (superseded where noted above)

# JobTracker — Handoff

**Last updated:** 2026-09-24 · **Branch:** `main` · **HEAD:** `8ee0600`

Written for whoever picks this up next, human or agent. It covers what works,
what does not, how to run it, and the non-obvious things that will otherwise
cost you an hour each.

---

## 1. What this is

A personal job-application tracker with three inputs feeding one Postgres
database, surfaced through a React dashboard:

| Pipeline | What it does | State |
|---|---|---|
| **Scraper** | Pulls a public internship listings JSON, dedupes, upserts | Working |
| **Email** | Gmail push → Pub/Sub → LLM classification → status transition | Code complete, **not connected to a real inbox** |
| **Dashboard** | Kanban board + opportunity queue | Working |

---

## 2. Status at a glance

| Area | State | Notes |
|---|---|---|
| Database schema | Done | Migrations `001`, `002` |
| Backend API | Done | 9 routes, all exercised against live Postgres |
| Scraper | Done | Ingests ~15k live listings, idempotent |
| Email pipeline | Code done, unproven | Verified with live Gemini + synthetic emails; never seen a real Gmail message |
| Frontend | Done | Verified in a browser |
| Local Docker stack | Done | `docker compose up -d --build` |
| Tests | 78 passing | **No coverage of API routes** |
| CI | Green | Lint + tests + frontend build |
| **Google Cloud setup** | **Not started** | Blocks real email |
| **AWS deployment** | **Not viable** | No compute provisioned for the backend |
| README | **Wrong** | Describes a different application |

---

## 3. Running it locally

```bash
cp .env.example .env          # then set LLM_API_KEY
docker compose up -d --build
```

- Frontend: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>

You need Docker. `psql` is handy but optional.

### Environment

The only value required for a working stack is `LLM_API_KEY`. Get a free one
at <https://aistudio.google.com> — no credit card. Defaults point at Gemini's
OpenAI-compatible endpoint; `LLM_BASE_URL` and `LLM_MODEL` switch providers
without code changes.

`POSTGRES_HOST_PORT` exists because a locally installed Postgres commonly owns
5432. The committed default is 5432; this machine's `.env` pins 5433. The
container-internal port never changes, so the backend is unaffected.

### Running tests

```bash
# Backend (a venv already exists at backend/.venv on this machine)
backend/.venv/Scripts/python.exe -m pytest backend/tests/ -q
backend/.venv/Scripts/python.exe -m ruff check backend/src backend/tests

# Frontend
cd frontend && npm run lint && npm run build
```

---

## 4. Landmines

Every one of these cost real time. Read before debugging anything.

**`docker compose restart` does not re-read `.env`.** It restarts the
container with its existing config. After changing `.env` you need
`docker compose up -d backend` to recreate it. Conversely, `up -d` with no
config change is a **no-op that leaves old Python running** — the source is
bind-mounted but uvicorn has no `--reload`, so after editing backend code you
need `restart`. Changed env → `up -d`. Changed code → `restart`. Changed both
→ `up -d` then `restart`.

**Migrations only auto-apply to a fresh volume.** They are mounted into the
Postgres entrypoint, which runs `/docker-entrypoint-initdb.d` exactly once at
cluster init. A new migration against an existing database must be applied by
hand:

```bash
docker compose exec -T db psql -U jobtracker -d jobtracker \
  -v ON_ERROR_STOP=1 < backend/src/db/migrations/00X_whatever.sql
```

All migrations are written to be idempotent, because `infra/scripts/setup_db.sh`
replays every `.sql` on each run. Keep that property.

**`.gitignore` has a blanket `*.sql` rule.** There is a negation for
`backend/src/db/migrations/*.sql`. Any migration placed elsewhere will be
silently invisible to `git add`. This is almost certainly why the schema did
not exist in the first place.

**`main.py` swallows router import errors.** The loop at `src/main.py:75`
catches `ModuleNotFoundError`/`AttributeError`, logs a warning, and continues.
A syntax error or bad import in a router means that router silently vanishes
and you get 404s with a healthy-looking app. If routes go missing, check the
startup log for `Skipping router`, or import the module directly. *This is
still live and is worth removing once the routers are stable.*

**Call `/api/applications/` with the trailing slash.** Without it FastAPI
issues a 307 whose `Location` is built from the proxied `Host`, i.e.
`http://backend:8000/...` — a hostname that resolves only inside the Docker
network. Requests fail in the browser with a DNS error.

**Ruff's rule set is pinned in `backend/pyproject.toml`.** CI installs an
unpinned ruff whose defaults widen between releases. Do not remove the
explicit `select`; `B008` in particular must stay ignored or every FastAPI
`Depends()` is flagged.

**Gemini free-tier quotas differ sharply by model.** `gemini-3.8-flash`
returned 429 on the very first call; `gemini-3.1-flash-lite` (the default) has
a much higher allowance and is plenty for email classification.

**FastAPI wraps included routers in `_IncludedRouter` objects.** Iterating
`app.routes` will not show router endpoints. Use `app.openapi()["paths"]`.

---

## 5. Map

```
backend/src/
  main.py                     app factory; silently skips broken routers (see §4)
  core/config.py              pydantic-settings; LLM_* supersede OPENAI_*
  core/state_machine.py       ApplicationStatus + VALID_TRANSITIONS + find_transition_path
  db/database.py              raw asyncpg pool — NOT SQLAlchemy, despite the README
  db/models.py                Pydantic schemas only, no ORM
  db/migrations/              plain .sql, applied in filename order
  api/dependencies.py         get_db, verify_pubsub_token (OIDC + shared-secret)
  api/routes/applications.py  CRUD, stats, filtering/paging
  api/routes/scraper.py       manual trigger; last-run state is IN MEMORY (see §6)
  api/routes/webhooks.py      Gmail push handler, tiered matching, watch registration
  email_pipeline/
    gmail_service.py          headless auth only; never starts a consent flow
    extractor.py              LLM call via cached AsyncOpenAI client
    schemas.py                ApplicationEvent + EVENT_TYPE_TO_STATUS
  scripts/bootstrap_gmail_token.py   one-time OAuth, run on a machine with a browser

frontend/src/
  types/index.ts              MUST mirror ApplicationStatus in state_machine.py
  services/api.ts             axios; repeated-param serialisation for status filters
  hooks/useApplications.ts    server-side filtering/paging, optimistic updates
  components/common/Toast.tsx transient errors
```

### Domain rules worth knowing

- `ApplicationStatus` has **10** values and lives in three places that must
  agree: `state_machine.py`, the `application_status` Postgres enum in
  `001_init.sql`, and `frontend/src/types/index.ts`. They drifted before and
  applications silently disappeared from the UI.
- Email-driven transitions accept any destination reachable by a **legal
  chain**, not just a direct edge, because offers arrive without anything ever
  marking the application `INTERVIEWED`. Terminal states stay terminal. The
  manual `PATCH` route remains strict single-step.
- Application matching is tiered: `email_thread_id` → company+role → company.
  Never match on company alone; it updates the wrong row when you have applied
  to a company more than once.

---

## 6. What is left

### A. Google Cloud setup — blocks real email *(next up)*

Everything on the code side is done. What remains is account configuration:

1. GCP project; enable the **Gmail API** and **Pub/Sub**.
2. OAuth **Desktop app** client → download `credentials.json`. Add yourself as
   a test user while the app is in Testing.
3. Mint the token on a machine with a browser:
   ```bash
   python backend/scripts/bootstrap_gmail_token.py \
     --credentials credentials.json --output backend/secrets/token.json
   ```
   `backend/secrets/` is already mounted read-only at `/app/secrets` and
   gitignored. Set `GOOGLE_CREDENTIALS_JSON=/app/secrets/token.json`.
4. Create the Pub/Sub topic, grant `gmail-api-push@system.gserviceaccount.com`
   the Publisher role on it, and create a **push** subscription pointing at
   `<public-url>/api/webhooks/gmail`.
5. Set `PUBSUB_AUDIENCE` (and ideally `PUBSUB_SERVICE_ACCOUNT_EMAIL`) so the
   endpoint verifies a real OIDC token instead of the dev shared secret.
6. `POST /api/webhooks/gmail/watch` to start delivery. **Watches expire after
   7 days** — schedule this daily or notifications stop with no error anywhere.

The webhook must be publicly reachable. A tunnel (ngrok/cloudflared) is the
fast path for proving it against a real inbox; a real deployment is §B.

### B. Deployment — currently not viable

- **No compute for the backend.** Terraform provisions a VPC, RDS, both
  Lambdas, API Gateway and EventBridge, but nothing that runs FastAPI. The
  email Lambda forwards to `BACKEND_API_URL`, which nothing deploys. Needs ECS
  Fargate or App Runner plus a load balancer, then wire the outputs.
- **`deploy.yml` never applies.** It runs `terraform plan` only, and builds
  Docker images that are never pushed to a registry. No ECR repository exists.
- **`infra/aws/lambda/scraper_cron/handler.py` is a stub** (line 90). Simplest
  fix: have it POST to `/api/scraper/run`, as the email Lambda already does.
- **Scraper run state is a module-level dict** (`scraper.py:29`). Lost on
  restart and inconsistent across the Dockerfile's two uvicorn workers. Move it
  to a table.
- No `docker-compose.prod.yml`, though the README references one.

### C. Tests and docs

- **No API route tests.** 78 tests cover the state machine, scraper, extractor
  and the webhook's helper functions, but nothing exercises the HTTP layer —
  which is exactly where the surviving bugs were found. `httpx.AsyncClient`
  against the app with a test database is the gap.
- **The README describes a different application.** It documents
  `/api/v1/jobs` (actual: `/api/applications`), `backend/app/` (actual:
  `backend/src/`), `infrastructure/` (actual: `infra/`), SQLAlchemy and Alembic
  (neither is used or installed), plus `/api/v1/emails` and two analytics
  endpoints that do not exist. Rewrite it against reality.
- No `LICENSE` file, though the README claims MIT.

### D. Smaller items

- Nine Kanban columns need horizontal scrolling; consider collapsing terminal
  states behind a toggle.
- No application detail view. `getApplication` exists and is unused.
- Frontend has no test runner at all.
- A test row (`Northwind Systems / Site Reliability Engineer`) and three
  `Vertex Labs` rows are demo data in the local database.

---

## 7. Conventions

- Commits explain **why**, and state what was actually verified. Tracked
  attribution: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Comments explain non-obvious reasoning, not mechanics. Several in this
  codebase record a bug that a future edit could reintroduce — keep those.
- Verify against the running stack, not just the test suite. Every significant
  bug found so far survived because nothing had actually run the code path.
