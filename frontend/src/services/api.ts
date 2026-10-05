import axios from 'axios';
import {
  Application,
  ApplicationCreate,
  ApplicationStats,
  ApplicationStatus,
  AuthConfig,
  CurrentUser,
  EmailActivity,
  Listing,
  Paged,
  ScraperRun,
} from '../types';

/** Query parameters accepted by GET /api/applications. */
export interface ListApplicationsParams {
  /** One or many statuses; several are sent as repeated `status` params. */
  status?: ApplicationStatus | ApplicationStatus[];
  search?: string;
  sort_by?: 'created_at' | 'updated_at' | 'company' | 'role' | 'status';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

/** Query parameters accepted by GET /api/listings. */
export interface ListListingsParams {
  search?: string;
  sort_by?: 'created_at' | 'date_posted' | 'company' | 'role';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

const api = axios.create({
  baseURL: '/api',
  // FastAPI reads repeated keys (?status=A&status=B). Axios would otherwise
  // serialise arrays as `status[]=A`, which the backend does not recognise.
  paramsSerializer: { indexes: null },
  // The backend refuses state-changing requests without this header. Other
  // sites cannot add it to a request without a CORS grant they do not have,
  // so it stops them acting with the user's session cookie.
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
});

/**
 * Called when any request comes back 401, i.e. the session has expired or
 * been revoked. The auth provider registers itself here to return the user
 * to the sign-in page.
 */
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (handler: (() => void) | null) => {
  onUnauthorized = handler;
};

api.interceptors.response.use(undefined, (error) => {
  if (axios.isAxiosError(error) && error.response?.status === 401) onUnauthorized?.();
  return Promise.reject(error);
});

const paged = <T,>(data: T[], header: unknown): Paged<T> => {
  const total = header !== undefined ? Number(header) : data.length;
  return { items: data, total: Number.isNaN(total) ? data.length : total };
};

/**
 * Fetch a page of applications along with the total number that match.
 *
 * The total comes from the X-Total-Count header. Callers need it because the
 * scraped backlog runs to tens of thousands of rows and the API caps a page
 * at 200 — the UI previously requested no page at all and silently showed
 * only the first 50 of everything.
 */
export const getApplications = async (
  params?: ListApplicationsParams,
): Promise<Paged<Application>> => {
  const response = await api.get<Application[]>('/applications/', { params });
  return paged(response.data, response.headers['x-total-count']);
};

/** Listings the signed-in user has not applied to yet. */
export const getListings = async (params?: ListListingsParams): Promise<Paged<Listing>> => {
  const response = await api.get<Listing[]>('/listings/', { params });
  return paged(response.data, response.headers['x-total-count']);
};

export const applyToListing = async (listingId: string) => {
  const response = await api.post<Application>(`/listings/${listingId}/apply`);
  return response.data;
};

export const getApplication = async (id: string) => {
  const response = await api.get<Application>(`/applications/${id}`);
  return response.data;
};

export const createApplication = async (data: ApplicationCreate) => {
  const response = await api.post<Application>('/applications/', data);
  return response.data;
};

export const updateApplication = async (id: string, data: Partial<Application>) => {
  const response = await api.patch<Application>(`/applications/${id}`, data);
  return response.data;
};

export const deleteApplication = async (id: string) => {
  await api.delete(`/applications/${id}`);
};

export const getStats = async () => {
  const response = await api.get<ApplicationStats>('/applications/stats/summary');
  return response.data;
};

export const triggerScraper = async () => {
  const response = await api.post('/scraper/run');
  return response.data;
};

export const getScraperStatus = async () => {
  const response = await api.get<ScraperRun>('/scraper/status');
  return response.data;
};

// ── Auth ──────────────────────────────────────────────────────────────────

export const getAuthConfig = async () => {
  const response = await api.get<AuthConfig>('/auth/config');
  return response.data;
};

export const getMe = async () => {
  const response = await api.get<CurrentUser>('/auth/me');
  return response.data;
};

export const logout = async () => {
  await api.post('/auth/logout');
};

export const devLogin = async (email: string) => {
  await api.post('/auth/dev-login', { email });
};

/** Full-page navigations: Google's consent screen cannot be reached by XHR. */
export const GOOGLE_SIGN_IN_URL = '/api/auth/login';
export const GMAIL_CONNECT_URL = '/api/gmail/connect';

// ── Gmail ─────────────────────────────────────────────────────────────────

export const disconnectGmail = async () => {
  await api.delete('/gmail');
};

export const getEmailActivity = async () => {
  const response = await api.get<EmailActivity[]>('/gmail/activity');
  return response.data;
};

/** Extract a human-readable message from an axios error. */
export const errorMessage = (err: unknown, fallback: string): string => {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (err.response?.status === 409) return 'That change conflicts with the current status.';
    return err.message;
  }
  return err instanceof Error ? err.message : fallback;
};

export default api;
