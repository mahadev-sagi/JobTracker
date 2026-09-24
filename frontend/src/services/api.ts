import axios from 'axios';
import {
  Application,
  ApplicationCreate,
  ApplicationStats,
  ApplicationStatus,
  Paged,
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

const api = axios.create({
  baseURL: '/api',
  // FastAPI reads repeated keys (?status=A&status=B). Axios would otherwise
  // serialise arrays as `status[]=A`, which the backend does not recognise.
  paramsSerializer: { indexes: null },
});

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
  const header = response.headers['x-total-count'];
  const total = header !== undefined ? Number(header) : response.data.length;
  return { items: response.data, total: Number.isNaN(total) ? response.data.length : total };
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
