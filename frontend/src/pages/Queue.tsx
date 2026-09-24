import { useEffect, useState } from 'react';
import QueueFilters from '../components/queue/QueueFilters';
import QueueTable from '../components/queue/QueueTable';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useToast } from '../components/common/Toast';
import { useApplications } from '../hooks/useApplications';
import { ApplicationStatus } from '../types';
import * as api from '../services/api';
import { Play, ChevronLeft, ChevronRight } from 'lucide-react';

const PAGE_SIZE = 50;

const Queue = () => {
  const { notify } = useToast();
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [isScraping, setIsScraping] = useState(false);

  // Debounce so a search hits the API once the user stops typing, rather
  // than on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Filtering and paging run on the server. Previously this fetched an
  // unfiltered first page and filtered it in the browser, so it could only
  // ever surface whatever UNAPPLIED rows happened to fall in the newest 50.
  const { applications, total, loading, error, updateStatus, refetch } = useApplications({
    status: ApplicationStatus.UNAPPLIED,
    search: search || undefined,
    // date_posted is not an allowed sort column on the API; created_at is the
    // closest proxy for "newest listings first".
    sort_by: 'created_at',
    order: 'desc',
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const handleMarkApplied = async (id: string) => {
    try {
      await updateStatus(id, ApplicationStatus.APPLIED);
      notify('Marked as applied.', 'success');
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Failed to update status.');
    }
  };

  const handleRunScraper = async () => {
    try {
      setIsScraping(true);
      await api.triggerScraper();
      notify('Scraper started. New listings will appear shortly.', 'success');
      // The run is asynchronous on the backend; give it a moment before
      // reloading so the first batch of inserts is visible.
      setTimeout(refetch, 4000);
    } catch (err) {
      notify(api.errorMessage(err, 'Failed to run the scraper.'));
    } finally {
      setIsScraping(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstShown = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastShown = Math.min(total, page * PAGE_SIZE + applications.length);

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Opportunity Queue
          </h1>
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
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2" />
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

      <QueueFilters searchTerm={searchInput} onSearchChange={setSearchInput} />

      {error && (
        <div className="mb-4 p-3 rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 text-sm text-red-800 dark:text-red-200">
          {error}
        </div>
      )}

      <div className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        {loading
          ? 'Loading…'
          : total === 0
            ? 'No opportunities found'
            : `Showing ${firstShown}–${lastShown} of ${total.toLocaleString()} opportunities`}
      </div>

      {loading && applications.length === 0 ? (
        <LoadingSpinner />
      ) : (
        <QueueTable applications={applications} onMarkApplied={handleMarkApplied} />
      )}

      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || loading}
            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md border border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            Previous
          </button>

          <span className="text-sm text-gray-500 dark:text-gray-400">
            Page {page + 1} of {totalPages.toLocaleString()}
          </span>

          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1 || loading}
            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md border border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next
            <ChevronRight className="w-4 h-4 ml-1" />
          </button>
        </div>
      )}
    </div>
  );
};

export default Queue;
