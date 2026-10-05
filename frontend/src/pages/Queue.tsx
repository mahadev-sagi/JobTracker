import { useCallback, useEffect, useState } from 'react';
import QueueFilters from '../components/queue/QueueFilters';
import QueueTable from '../components/queue/QueueTable';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useToast } from '../components/common/Toast';
import { useAuth } from '../auth/AuthContext';
import { Listing, ScraperRun } from '../types';
import * as api from '../services/api';
import { Play, ChevronLeft, ChevronRight } from 'lucide-react';

const PAGE_SIZE = 50;

const Queue = () => {
  const { notify } = useToast();
  const { user } = useAuth();
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [listings, setListings] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isScraping, setIsScraping] = useState(false);
  const [lastRun, setLastRun] = useState<ScraperRun | null>(null);

  // Debounce so a search hits the API once the user stops typing, rather
  // than on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // The shared job board minus whatever this user has already applied to.
  // Filtering and paging run on the server; the board holds tens of
  // thousands of listings.
  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await api.getListings({
        search: search || undefined,
        sort_by: 'created_at',
        order: 'desc',
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setListings(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(api.errorMessage(err, 'Failed to load listings'));
    } finally {
      setLoading(false);
    }
  }, [search, page]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.getScraperStatus().then(setLastRun).catch(() => setLastRun(null));
  }, []);

  const handleMarkApplied = async (id: string) => {
    const previous = listings;
    setListings((rows) => rows.filter((row) => row.id !== id));
    setTotal((t) => Math.max(0, t - 1));
    try {
      await api.applyToListing(id);
      notify('Added to your applications.', 'success');
    } catch (err) {
      setListings(previous);
      setTotal((t) => t + 1);
      notify(api.errorMessage(err, 'Failed to mark as applied.'));
    }
  };

  const handleRunScraper = async () => {
    try {
      setIsScraping(true);
      await api.triggerScraper();
      notify('Scraper started. New listings will appear shortly.', 'success');
      // The run is asynchronous on the backend; give it a moment before
      // reloading so the first batch of inserts is visible.
      setTimeout(() => {
        load();
        api.getScraperStatus().then(setLastRun).catch(() => undefined);
      }, 4000);
    } catch (err) {
      notify(api.errorMessage(err, 'Failed to run the scraper.'));
    } finally {
      setIsScraping(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstShown = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastShown = Math.min(total, page * PAGE_SIZE + listings.length);
  const lastUpdated = lastRun?.status === 'completed' ? lastRun.finished_at : null;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Opportunity Queue
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Open roles you haven't applied to yet
            {lastUpdated && ` · listings updated ${new Date(lastUpdated).toLocaleString()}`}
          </p>
        </div>

        {/* Listings are shared, and refresh daily on their own; only an
            admin can force a run. */}
        {user?.is_admin && (
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
        )}
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

      {loading && listings.length === 0 ? (
        <LoadingSpinner />
      ) : (
        <QueueTable listings={listings} onMarkApplied={handleMarkApplied} />
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
