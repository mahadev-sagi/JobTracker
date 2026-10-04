# Current handoff - 2026-09-27

This section supersedes the historical notes below.

## Running deployment

The local personal deployment is running at http://localhost:5173, using:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --build
```

- Compiled React app served by nginx; backend code baked into its image.
- Existing database volume retained; API reports 15,160 active rows.
- Ports 5173, 8000, 8080, and 5433 bound to 127.0.0.1 only.
- Existing host cloudflared process targets http://localhost:8080.
- Gateway permits only health and Gmail push; local checks confirmed 404 for
  applications, docs, and watch registration, and 401 for anonymous push.
- Public tunnel URL was not recovered or tested externally in this session.
- Production override uses one backend worker because scraper run state is
  still in memory. It resets on restart.

## Changes and validation

Removed silent router-import failure. Webhook authentication now fails closed
in development too. Gmail history and classifier failures propagate; failed
batches return 503 without advancing the cursor. Application updates and the
processed-message marker share a transaction. This fixes several silent-loss
paths, but does not establish complete delivery correctness (see below).

85 backend tests pass, including new HTTP authentication and retry tests.
Backend Ruff, frontend ESLint, and production frontend build pass. Rebuilt
Docker deployment is healthy; dashboard, proxied list/stats, and gateway
restrictions were checked against the running stack. No live Gmail or LLM
request was made. README now describes the actual application and deployment.

## Requires user input / unfinished

Asked whether deployment should stay on this PC or move to an always-on cloud
server; no answer yet. No cloud resources were provisioned.

Gmail remains unconnected: GOOGLE_CLOUD_PROJECT_ID, GMAIL_USER_EMAIL, and
GOOGLE_CREDENTIALS_JSON are empty; backend/secrets has no OAuth token. Asked
whether the user has a project and a downloaded Desktop OAuth credentials
file. README includes setup steps. Do not paste credentials into chat.

Before declaring Gmail ready for ongoing use:
- Configure authenticated OIDC push, Gmail OAuth, a stable tunnel, and daily
  watch renewal; run an actual incoming-mail test with the user.
- Serialize overlapping pushes and prevent older notifications from moving
  the history cursor backwards. Current processing is synchronous and can
  exceed push request deadlines for large batches.
- Fix ambiguous company-only matching: current fallback can select the wrong
  application when multiple roles exist. The old notes overstate this fix.
- Handle expired Gmail history IDs with an explicit recovery procedure.

Dashboard has no authentication; keep it local until an authenticated access
layer is in place. AWS Terraform remains incomplete. Automated backups and
persistent scraper run state are not configured. The PC and Docker must stay
running for this deployment to be available.

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
