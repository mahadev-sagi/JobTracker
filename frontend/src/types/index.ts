/**
 * Shared API types.
 *
 * These mirror the backend exactly. ApplicationStatus must stay in step with
 * `ApplicationStatus` in backend/src/core/state_machine.py and the
 * `application_status` enum in 001_init.sql — when it drifted previously, four
 * statuses were missing here and applications in those states silently
 * disappeared from the UI.
 */

export enum ApplicationStatus {
  UNAPPLIED = 'UNAPPLIED',
  APPLIED = 'APPLIED',
  OA_RECEIVED = 'OA_RECEIVED',
  INTERVIEW_SCHEDULED = 'INTERVIEW_SCHEDULED',
  INTERVIEWED = 'INTERVIEWED',
  OFFERED = 'OFFERED',
  ACCEPTED = 'ACCEPTED',
  REJECTED = 'REJECTED',
  WITHDRAWN = 'WITHDRAWN',
  GHOSTED = 'GHOSTED',
}

/** Statuses that belong on the pipeline board. UNAPPLIED lives in the Queue. */
export const BOARD_STATUSES: ApplicationStatus[] = [
  ApplicationStatus.APPLIED,
  ApplicationStatus.OA_RECEIVED,
  ApplicationStatus.INTERVIEW_SCHEDULED,
  ApplicationStatus.INTERVIEWED,
  ApplicationStatus.OFFERED,
  ApplicationStatus.ACCEPTED,
  ApplicationStatus.REJECTED,
  ApplicationStatus.WITHDRAWN,
  ApplicationStatus.GHOSTED,
];

/** Human-readable column and badge labels. */
export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  [ApplicationStatus.UNAPPLIED]: 'Unapplied',
  [ApplicationStatus.APPLIED]: 'Applied',
  [ApplicationStatus.OA_RECEIVED]: 'Online Assessment',
  [ApplicationStatus.INTERVIEW_SCHEDULED]: 'Interview Scheduled',
  [ApplicationStatus.INTERVIEWED]: 'Interviewed',
  [ApplicationStatus.OFFERED]: 'Offer',
  [ApplicationStatus.ACCEPTED]: 'Accepted',
  [ApplicationStatus.REJECTED]: 'Rejected',
  [ApplicationStatus.WITHDRAWN]: 'Withdrawn',
  [ApplicationStatus.GHOSTED]: 'Ghosted',
};

/**
 * One row of the `applications` table, as returned by the API.
 *
 * Field names are the API's, not invented ones: the listing link is `url`,
 * and there is no `date_applied` column.
 */
export interface Application {
  id: string;
  /** The shared listing this was applied from, if any. */
  listing_id?: string | null;
  company: string;
  role: string;
  status: ApplicationStatus;
  location?: string | null;
  url?: string | null;
  date_posted?: string | null;
  source?: string | null;
  notes?: string | null;
  email_thread_id?: string | null;
  created_at: string;
  updated_at: string;
}

/** Payload for POST /api/applications. */
export interface ApplicationCreate {
  company: string;
  role: string;
  location?: string;
  url?: string;
  date_posted?: string;
  source?: string;
  notes?: string;
  status?: ApplicationStatus;
}

export interface ApplicationStats {
  total: number;
  applied: number;
  interviews: number;
  offers: number;
  rejected: number;
  by_status: Record<ApplicationStatus, number>;
}

export interface Column {
  id: ApplicationStatus;
  title: string;
}

/** A page of results plus the unpaginated total from X-Total-Count. */
export interface Paged<T> {
  items: T[];
  total: number;
}

/** A shared, scraped job-board posting. */
export interface Listing {
  id: string;
  company: string;
  role: string;
  location?: string | null;
  url?: string | null;
  date_posted?: string | null;
  source?: string | null;
  created_at: string;
}

export interface GmailConnection {
  email_address: string;
  /** 'active', or 'revoked' when Google access must be granted again. */
  status: 'active' | 'revoked';
  last_synced_at: string | null;
  watch_expires_at: string | null;
  last_error: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  name: string | null;
  picture_url: string | null;
  is_admin: boolean;
  gmail: GmailConnection | null;
  /** False until the server has a Google OAuth client and encryption key. */
  gmail_available: boolean;
}

export interface AuthConfig {
  google: boolean;
  dev_login: boolean;
}

/** One email the pipeline acted on, from GET /api/gmail/activity. */
export interface EmailActivity {
  message_id: string;
  outcome: 'updated' | 'unchanged' | 'created' | 'ambiguous';
  event_type: string | null;
  company: string | null;
  subject: string | null;
  processed_at: string;
  application_id: string | null;
  role: string | null;
  status: ApplicationStatus | null;
}

export interface ScraperRun {
  status: 'idle' | 'running' | 'completed' | 'failed';
  started_at?: string;
  finished_at?: string | null;
  new_inserted?: number;
  error?: string | null;
}
