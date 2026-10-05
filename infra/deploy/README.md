# Deploying JobTracker to one server

The production stack is three containers on one small Linux server:

| Container | Image | Role |
|---|---|---|
| `web` | `ghcr.io/<owner>/jobtracker-web` | Caddy: HTTPS, the compiled frontend, proxies `/api` |
| `backend` | `ghcr.io/<owner>/jobtracker-backend` | FastAPI, migrations at startup, scheduler |
| `db` | `postgres:16-alpine` | Data; not reachable from outside the server |

Measured on a test run: about 145 MB of memory in total, so a 1 GB instance
has ample room. Only ports 80 and 443 are public.

How updates flow: a push to `main` → CI → `.github/workflows/deploy.yml`
builds both images and pushes them to GitHub Container Registry → the
server's `update.sh` (cron, every 5 minutes) pulls the repository and images
and restarts only what changed. The server needs no GitHub credentials and
GitHub needs no access to the server.

## 1. Launch the server (AWS EC2)

1. **Stay on the free plan.** When creating the account, choose the
   **Free plan**, not the paid plan. Since mid-2025, new AWS accounts get
   sign-up credits (about $100–200, valid for 6 months) and a free-plan
   account is never charged beyond them. Usage just draws down the credits.
   When the credits or the 6 months run out, AWS asks you to upgrade; until
   you do, nothing is billed (and the account is eventually closed). Check
   the current terms on the sign-up page; they change.
   Accounts created before July 2025 have the older 12-month free tier
   instead, which covers one `t2.micro`/`t3.micro` and 30 GB of disk.
2. **Billing safety anyway:** Billing and Cost Management → Budgets → create
   a *zero spend* budget with an email alert. Billing → Credits shows what is
   left.
3. EC2 → **Launch instance**:
   - **Name:** `jobtracker`
   - **Image:** Ubuntu Server 24.04 LTS, 64-bit (x86)
   - **Instance type:** `t3.micro`, or whichever type the console marks
     *Free tier eligible* (x86 only; the images are not built for ARM)
   - **Key pair:** create one and save the `.pem` file somewhere safe
   - **Network:** allow SSH **from My IP only**, allow HTTPS and HTTP from the
     internet (HTTP is needed for certificate issuance and the redirect)
   - **Storage:** 20 GiB gp3 (stay at or under 30 GiB)
4. Note the instance's **public IPv4 address**.

What it uses: instance about $7.50, public IPv4 $3.60 and 20 GiB disk
$1.60, so about $13 a month of credits, or roughly $80 over the 6 months.

## 2. Set up the server

From PowerShell on your PC (OpenSSH is built into Windows):

```powershell
ssh -i path\to\key.pem ubuntu@PUBLIC_IP
```

Then on the server:

```bash
sudo git clone https://github.com/mahadev-sagi/JobTracker.git /opt/jobtracker
sudo bash /opt/jobtracker/infra/deploy/bootstrap.sh
```

This installs Docker, adds 2 GB of swap, turns on automatic security updates,
creates `/opt/jobtracker/infra/deploy/.env` with a generated database
password and encryption key, and installs the cron jobs.

## 3. Configure

```bash
sudo nano /opt/jobtracker/infra/deploy/.env
```

Fill in at least:

- `DOMAIN`: `yourname.duckdns.org`
- `ACME_EMAIL`: your email, for certificate problems
- `DUCKDNS_SUBDOMAIN` (just `yourname`) and `DUCKDNS_TOKEN` (shown at the
  top of duckdns.org once you sign in)
- `ADMIN_EMAILS`: your Google address
- `LLM_API_KEY`: needed for email classification only

Then point the name at the server and start:

```bash
sudo /opt/jobtracker/infra/deploy/duckdns.sh
cd /opt/jobtracker/infra/deploy && sudo docker compose up -d
sudo docker compose logs -f     # Ctrl+C to stop following
```

Within a minute Caddy obtains a certificate and `https://DOMAIN` loads. On a
new database the backend applies the schema and runs the first scrape
(a minute or two).

Until the Google settings are filled in (README, "Google setup"), the sign-in
page says sign-in is not configured. That is expected.

## Images

Images are rebuilt whenever `main` passes CI and are public, inheriting the
repository's visibility, so the server pulls them without credentials. If a
pull ever fails with "unauthorized", check GitHub → your profile →
**Packages** → each package → Package settings → visibility. The images hold
no secrets; those live only in the server's `.env`.

## Day to day

| Task | Command (in `/opt/jobtracker/infra/deploy`) |
|---|---|
| Status | `sudo docker compose ps` |
| Logs | `sudo docker compose logs -f backend` |
| Update now | `sudo ./update.sh` |
| Back up now | `sudo ./backup.sh` |
| Restart | `sudo docker compose restart` |
| Apply `.env` changes | `sudo docker compose up -d` |

Script logs: `/var/log/jobtracker-{update,backup,duckdns}.log`.

**Backups** run nightly at 03:30 UTC to `/var/backups/jobtracker` and keep
the last 14. They live on the same disk as the database, so also keep a copy
elsewhere: set `BACKUP_S3_URI`, or now and then run
`scp -i key.pem ubuntu@PUBLIC_IP:/var/backups/jobtracker/* .` from your PC.
**Also save a copy of `TOKEN_ENCRYPTION_KEY`** from `.env`. Without it, a
restored database's Gmail connections cannot be read and every user must
reconnect.

**Restore** a backup into a fresh stack:

```bash
sudo docker compose exec -T db pg_restore -U jobtracker -d jobtracker --clean --if-exists --no-owner < /var/backups/jobtracker/FILE.dump
sudo docker compose restart backend
```

**Roll back** a bad release: set `IMAGE_TAG` in `.env` to an earlier
commit's full SHA (every image is also tagged by commit), then
`sudo docker compose up -d`. Set it back to `latest` to resume updates.
