-- =============================================================================
-- 003_multi_user.sql — accounts, shared listings, per-user applications
--
-- Until now one `applications` table held both the scraped job board and the
-- owner's own applications (an "application" was a listing whose status had
-- moved past UNAPPLIED). With several users those have to separate: listings
-- are shared, applications belong to one user.
--
-- Unlike 001/002 this migration is NOT safe to replay. It is applied exactly
-- once by the runner in src/db/migrate.py, which records it in
-- schema_migrations.
--
-- Existing data: scraped rows are copied into `listings`; the old table is kept
-- as `legacy_applications` so the owner's applications can be claimed after
-- their first sign-in (backend/scripts/claim_legacy_data.py). On a fresh
-- database it is empty and dropped at the end.
-- =============================================================================

-- ── Accounts ─────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Google's stable account id. Email addresses can change; `sub` does not.
    google_sub    VARCHAR(255) NOT NULL UNIQUE,
    email         VARCHAR(320) NOT NULL UNIQUE,
    name          VARCHAR(255),
    picture_url   VARCHAR(2048),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Server-side sessions. Only a SHA-256 of the cookie value is stored, so a
-- database dump does not hand out live sessions.
CREATE TABLE sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_sessions_user_id ON sessions (user_id);
CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

-- ── Shared job board ─────────────────────────────────────────────────────────
CREATE TABLE listings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company     VARCHAR(255) NOT NULL,
    role        VARCHAR(255) NOT NULL,
    location    VARCHAR(255),
    url         VARCHAR(2048),
    date_posted DATE,
    source      VARCHAR(100),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Same dedup rules the scraper relied on in 001: URL when present, otherwise
-- company + role + location. The scraper's bare ON CONFLICT DO NOTHING catches
-- either.
CREATE UNIQUE INDEX uq_listings_url ON listings (url) WHERE url IS NOT NULL;
CREATE UNIQUE INDEX uq_listings_company_role_location
    ON listings (LOWER(company), LOWER(role), LOWER(COALESCE(location, '')));
CREATE INDEX ix_listings_created_at ON listings (created_at DESC);

CREATE TRIGGER trg_listings_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ── Retire the single-user table ─────────────────────────────────────────────
ALTER TABLE applications RENAME TO legacy_applications;
DROP TRIGGER IF EXISTS trg_applications_updated_at ON legacy_applications;
-- Index names are schema-wide, so the old ones would collide with the new
-- table's below.
DROP INDEX IF EXISTS uq_applications_url;
DROP INDEX IF EXISTS uq_applications_company_role_location;
DROP INDEX IF EXISTS ix_applications_status;
DROP INDEX IF EXISTS ix_applications_updated_at;
DROP INDEX IF EXISTS ix_applications_created_at;
DROP INDEX IF EXISTS ix_applications_email_thread_id;

-- Every scraped row is public job-board data, whatever its old status. Manual
-- and email-created rows are private to the owner and are not shared.
INSERT INTO listings (company, role, location, url, date_posted, source, created_at)
SELECT company, role, location, url, date_posted, source, created_at
FROM legacy_applications
WHERE deleted_at IS NULL AND source = 'SIMPLIFY_SCRAPER'
ON CONFLICT DO NOTHING;

-- ── Per-user applications ────────────────────────────────────────────────────
-- Listing fields are copied rather than joined: an application can exist with
-- no listing (added by hand or created from an email), and a user's record of
-- what they applied to should not change if the listing is later edited.
CREATE TABLE applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    listing_id      UUID REFERENCES listings (id) ON DELETE SET NULL,
    company         VARCHAR(255) NOT NULL,
    role            VARCHAR(255) NOT NULL,
    location        VARCHAR(255),
    url             VARCHAR(2048),
    date_posted     DATE,
    source          VARCHAR(100),
    status          application_status NOT NULL DEFAULT 'APPLIED',
    notes           TEXT,
    email_thread_id VARCHAR(255),
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One live application per listing per user; the queue relies on this.
CREATE UNIQUE INDEX uq_applications_user_listing
    ON applications (user_id, listing_id)
    WHERE listing_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX ix_applications_user_status
    ON applications (user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ix_applications_user_updated_at
    ON applications (user_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_applications_user_company
    ON applications (user_id, LOWER(company)) WHERE deleted_at IS NULL;
CREATE INDEX ix_applications_user_thread
    ON applications (user_id, email_thread_id) WHERE email_thread_id IS NOT NULL;

CREATE TRIGGER trg_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ── Gmail, per user ──────────────────────────────────────────────────────────
-- 002's tables assumed one mailbox and have never held production data.
DROP TABLE IF EXISTS gmail_sync_state;
DROP TABLE IF EXISTS processed_emails;

CREATE TABLE gmail_accounts (
    user_id                 UUID PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    email_address           VARCHAR(320) NOT NULL UNIQUE,
    -- Fernet-encrypted with TOKEN_ENCRYPTION_KEY. A refresh token grants
    -- standing read access to someone's mailbox, so it is never stored plain.
    refresh_token_encrypted TEXT NOT NULL,
    -- Last Gmail history id fully processed. Opaque token; compared only via
    -- ::numeric when guarding against moving backwards.
    last_history_id         VARCHAR(64),
    -- When the mailbox was last fully processed. Used to recover by date when
    -- Gmail has discarded the history behind last_history_id.
    last_synced_at          TIMESTAMPTZ,
    -- Gmail watches lapse after 7 days; the scheduler renews from this.
    watch_expires_at        TIMESTAMPTZ,
    -- active | revoked. Revoked accounts are skipped until reconnected.
    status                  VARCHAR(20) NOT NULL DEFAULT 'active',
    last_error              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_gmail_accounts_updated_at
    BEFORE UPDATE ON gmail_accounts
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Every message the pipeline has looked at, and what it did. Doubles as the
-- dedup guard (Pub/Sub redelivers) and as a record of emails that could not
-- be matched to an application unambiguously.
CREATE TABLE processed_emails (
    user_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    message_id     VARCHAR(255) NOT NULL,
    thread_id      VARCHAR(255),
    -- ignored | updated | unchanged | created | ambiguous
    outcome        VARCHAR(20) NOT NULL,
    application_id UUID REFERENCES applications (id) ON DELETE SET NULL,
    event_type     VARCHAR(50),
    company        VARCHAR(255),
    subject        TEXT,
    processed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, message_id)
);
CREATE INDEX ix_processed_emails_user_processed_at
    ON processed_emails (user_id, processed_at DESC);

-- ── Scraper runs ─────────────────────────────────────────────────────────────
-- Replaces the in-memory dict that reset on restart and disagreed between
-- uvicorn workers.
CREATE TABLE scraper_runs (
    id                 BIGSERIAL PRIMARY KEY,
    -- manual | scheduled
    trigger            VARCHAR(20) NOT NULL,
    -- running | completed | failed
    status             VARCHAR(20) NOT NULL,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at        TIMESTAMPTZ,
    jobs_found         INTEGER NOT NULL DEFAULT 0,
    new_inserted       INTEGER NOT NULL DEFAULT 0,
    duplicates_skipped INTEGER NOT NULL DEFAULT 0,
    error              TEXT
);
CREATE INDEX ix_scraper_runs_started_at ON scraper_runs (started_at DESC);
-- At most one run in flight, enforced by the database rather than a flag.
CREATE UNIQUE INDEX uq_scraper_runs_one_running
    ON scraper_runs ((status)) WHERE status = 'running';

-- ── Clean up on a fresh database ─────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM legacy_applications) THEN
        DROP TABLE legacy_applications;
    END IF;
END
$$;
