-- =============================================================================
-- 002_gmail_sync_state.sql — Gmail incremental-sync bookkeeping
--
-- Gmail's users.history.list returns changes *after* a given startHistoryId.
-- A push notification carries the mailbox's CURRENT historyId, so replaying
-- from it returns nothing and the triggering message is missed. Correct
-- incremental sync requires remembering the last id we actually processed.
--
-- Idempotent, for the same reasons as 001.
-- =============================================================================

CREATE TABLE IF NOT EXISTS gmail_sync_state (
    -- The mailbox address. One row per monitored inbox.
    email_address    VARCHAR(320) PRIMARY KEY,
    -- Last history id successfully processed. Gmail history ids are unsigned
    -- 64-bit, which exceeds BIGINT's positive range only in theory, but they
    -- are opaque tokens, so store them as text and never do arithmetic.
    last_history_id  VARCHAR(64),
    -- Expiry of the current users.watch registration. Gmail caps a watch at
    -- 7 days, so a renewal job reads this to decide when to re-register.
    watch_expires_at TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_gmail_sync_state_updated_at ON gmail_sync_state;
CREATE TRIGGER trg_gmail_sync_state_updated_at
    BEFORE UPDATE ON gmail_sync_state
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Lets the webhook skip messages it has already handled, which matters because
-- Pub/Sub delivers at-least-once and will redeliver on any non-200.
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id   VARCHAR(255) PRIMARY KEY,
    thread_id    VARCHAR(255),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_processed_emails_processed_at
    ON processed_emails (processed_at DESC);
