import { useState, useCallback, useEffect } from 'react';
import { Application, ApplicationStatus } from '../types';
import * as api from '../services/api';

export const useApplications = () => {
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchApplications = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getApplications();
      setApplications(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch applications');
    } finally {
      setLoading(false);
    }
  }, []);

  const updateStatus = async (id: string, status: ApplicationStatus) => {
    try {
      const updatedApp = await api.updateApplication(id, { status });
      setApplications(prev =>
        prev.map(app => (app.id === id ? { ...app, status } : app))
      );
      return updatedApp;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update application status');
      throw err;
    }
  };

  useEffect(() => {
    fetchApplications();
  }, [fetchApplications]);

  return { applications, loading, error, refetch: fetchApplications, updateStatus };
};
