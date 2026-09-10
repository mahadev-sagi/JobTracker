import React, { useState, useMemo } from 'react';
import QueueFilters from '../components/queue/QueueFilters';
import QueueTable from '../components/queue/QueueTable';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useApplications } from '../hooks/useApplications';
import { ApplicationStatus } from '../types';
import * as api from '../services/api';
import { Play } from 'lucide-react';

const Queue = () => {
  const { applications, loading, error, updateStatus, refetch } = useApplications();
  const [searchTerm, setSearchTerm] = useState('');
  const [isScraping, setIsScraping] = useState(false);

  const unappliedJobs = useMemo(() => {
    return applications
      .filter(app => app.status === ApplicationStatus.UNAPPLIED)
      .filter(app => {
        if (!searchTerm) return true;
        const term = searchTerm.toLowerCase();
        return (
          app.company.toLowerCase().includes(term) ||
          app.role.toLowerCase().includes(term)
        );
      })
      .sort((a, b) => {
        // Sort by date_posted descending if available
        if (a.date_posted && b.date_posted) {
          return new Date(b.date_posted).getTime() - new Date(a.date_posted).getTime();
        }
        return 0;
      });
  }, [applications, searchTerm]);

  const handleMarkApplied = async (id: string) => {
    try {
      await updateStatus(id, ApplicationStatus.APPLIED);
    } catch (err) {
      console.error('Failed to update status', err);
    }
  };

  const handleRunScraper = async () => {
    try {
      setIsScraping(true);
      await api.triggerScraper();
      await refetch();
    } catch (err) {
      console.error('Failed to run scraper', err);
      alert('Failed to run scraper. Make sure the backend is running.');
    } finally {
      setIsScraping(false);
    }
  };

  if (loading && applications.length === 0) return <LoadingSpinner />;
  if (error) return <div className="p-8 text-red-500">Error: {error}</div>;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Opportunity Queue</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Review and apply to new job opportunities
          </p>
        </div>
        
        <button
          onClick={handleRunScraper}
          disabled={isScraping}
          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isScraping ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
              Scraping...
            </>
          ) : (
            <>
              <Play className="w-4 h-4 mr-2" />
              Run Scraper
            </>
          )}
        </button>
      </div>

      <QueueFilters 
        searchTerm={searchTerm} 
        onSearchChange={setSearchTerm} 
      />
      
      <div className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        Showing {unappliedJobs.length} opportunities
      </div>

      <QueueTable 
        applications={unappliedJobs} 
        onMarkApplied={handleMarkApplied} 
      />
    </div>
  );
};

export default Queue;
