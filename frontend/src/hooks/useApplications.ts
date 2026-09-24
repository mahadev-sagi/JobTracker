import { useCallback, useEffect, useState } from 'react';
import { Application, ApplicationStatus } from '../types';
import * as api from '../services/api';

interface UseApplicationsOptions extends api.ListApplicationsParams {
  /** Skip the initial fetch until the caller is ready. */
  enabled?: boolean;
}

/**
 * Load a page of applications.
 *
 * Filtering and paging happen on the server. Doing it in the browser meant
 * fetching the default first page of 50 rows and filtering that, so almost
 * the entire backlog was invisible.
 */
export const useApplications = (options: UseApplicationsOptions = {}) => {
  const { enabled = true, status, search, sort_by, order, limit, offset } = options;

  const [applications, setApplications] = useState<Application[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  // Arrays are compared by identity, so a caller passing a literal would
  // re-trigger the effect forever. Serialise to a stable key.
  const statusKey = Array.isArray(status) ? status.join(',') : (status ?? '');

  const fetchApplications = useCallback(async () => {
    if (!enabled) return;
    try {
      setLoading(true);
      setError(null);
      const page = await api.getApplications({
        status,
        search,
        sort_by,
        order,
        limit,
        offset,
      });
      setApplications(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(api.errorMessage(err, 'Failed to fetch applications'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, statusKey, search, sort_by, order, limit, offset]);

  /**
   * Move an application to a new status.
   *
   * Updates optimistically and rolls back if the server refuses, which it
   * legitimately does for a transition the state machine disallows. The
   * error is returned to the caller to surface transiently rather than being
   * stored as page-level state, because a rejected drag used to replace the
   * whole dashboard with an error message.
   */
  const updateStatus = async (id: string, newStatus: ApplicationStatus) => {
    const previous = applications;
    setApplications((prev) =>
      prev.map((app) => (app.id === id ? { ...app, status: newStatus } : app)),
    );
    try {
      const updated = await api.updateApplication(id, { status: newStatus });
      setApplications((prev) => prev.map((app) => (app.id === id ? updated : app)));
      return updated;
    } catch (err) {
      setApplications(previous);
      throw new Error(api.errorMessage(err, 'Failed to update status'));
    }
  };

  const removeApplication = async (id: string) => {
    const previous = applications;
    setApplications((prev) => prev.filter((app) => app.id !== id));
    setTotal((t) => Math.max(0, t - 1));
    try {
      await api.deleteApplication(id);
    } catch (err) {
      setApplications(previous);
      setTotal(previous.length);
      throw new Error(api.errorMessage(err, 'Failed to delete application'));
    }
  };

  useEffect(() => {
    fetchApplications();
  }, [fetchApplications]);

  return {
    applications,
    total,
    loading,
    error,
    refetch: fetchApplications,
    updateStatus,
    removeApplication,
  };
};
