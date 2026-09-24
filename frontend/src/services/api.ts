import axios from 'axios';
import { Application, ApplicationStats, ApplicationStatus } from '../types';

/** Query parameters accepted by GET /api/applications. */
export interface ListApplicationsParams {
  status?: ApplicationStatus;
  search?: string;
  sort_by?: 'created_at' | 'updated_at' | 'company' | 'role' | 'status';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

const api = axios.create({
  baseURL: '/api',
});

export const getApplications = async (params?: ListApplicationsParams) => {
  const response = await api.get<Application[]>('/applications', { params });
  return response.data;
};

export const getApplication = async (id: string) => {
  const response = await api.get<Application>(`/applications/${id}`);
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

export default api;
