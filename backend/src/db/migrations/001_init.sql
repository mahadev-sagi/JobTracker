-- =============================================================================
-- 001_init.sql — initial JobTracker schema
--
-- Idempotent: infra/scripts/setup_db.sh re-runs every *.sql on each invocation,
-- and the Postgres entrypoint replays this file on a fresh volume, so every
-- statement guards against already existing.
-- =============================================================================

-- gen_random_uuid() lives in pgcrypto on PG < 13 and core on >= 13; the
-- extension is a no-op on modern servers but keeps older ones working.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Status enum ──────────────────────────────────────────────────────────────
-- Declared in pipeline order (not alphabetical) so `ORDER BY status` sorts the
-- way the Kanban board reads. Values mirror src/core/state_machine.py exactly.
DO $$
BEGIN
    CREATE TYPE application_status AS ENUM (
        'UNAPPLIED',
        'APPLIED',
        'OA_RECEIVED',
        'INTERVIEW_SCHEDULED',
        'INTERVIEWED',
        'OFFERED',
        'ACCEPTED',
        'REJECTED',
        'WITHDRAWN',
        'GHOSTED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

-- ── applications ─────────────────────────────────────────────────────────────
-- Column widths match the Field(max_length=...) constraints in src/db/models.py.
CREATE TABLE IF NOT EXISTS applications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company         VARCHAR(255) NOT NULL,
    role            VARCHAR(255) NOT NULL,
    location        VARCHAR(255),
    url             VARCHAR(2048),
    date_posted     DATE,
    source          VARCHAR(100),
    status          application_status NOT NULL DEFAULT 'UNAPPLIED',
    notes           TEXT,
    email_thread_id VARCHAR(255),
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Dedup constraints ────────────────────────────────────────────────────────
-- The scraper upsert (src/scraper/ingestion.py) uses a bare ON CONFLICT DO
-- NOTHING with no conflict target, which catches a violation of ANY unique
-- index below, including these partial ones.

-- A listing URL identifies a posting uniquely when present.
CREATE UNIQUE INDEX IF NOT EXISTS uq_applications_url
    ON applications (url)
    WHERE url IS NOT NULL AND deleted_at IS NULL;

-- Fallback for listings with no URL: same role at the same company and location
-- is the same posting. Case-insensitive because sources are inconsistent.
CREATE UNIQUE INDEX IF NOT EXISTS uq_applications_company_role_location
    ON applications (LOWER(company), LOWER(role), LOWER(COALESCE(location, '')))
    WHERE deleted_at IS NULL;

-- ── Query indexes ────────────────────────────────────────────────────────────
-- Every read path filters on `deleted_at IS NULL`, so the hot indexes are
-- partial on that predicate.
CREATE INDEX IF NOT EXISTS ix_applications_status
    ON applications (status)
    WHERE deleted_at IS NULL;

-- Default sort in GET /api/applications is `updated_at DESC`.
CREATE INDEX IF NOT EXISTS ix_applications_updated_at
    ON applications (updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_applications_created_at
    ON applications (created_at DESC)
    WHERE deleted_at IS NULL;

-- The webhook matches inbound email to an existing application by thread id.
CREATE INDEX IF NOT EXISTS ix_applications_email_thread_id
    ON applications (email_thread_id)
    WHERE email_thread_id IS NOT NULL;

-- ── updated_at maintenance ───────────────────────────────────────────────────
-- The PATCH route already sets updated_at = NOW() explicitly; this trigger
-- covers every other writer (webhook, scraper, manual psql).
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_applications_updated_at ON applications;
CREATE TRIGGER trg_applications_updated_at
    BEFORE UPDATE ON applications
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
