import { useCallback, useEffect, useState } from 'react';
import KanbanBoard from '../components/kanban/KanbanBoard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import AddApplicationDialog from '../components/common/AddApplicationDialog';
import { useToast } from '../components/common/Toast';
import { useApplications } from '../hooks/useApplications';
import * as api from '../services/api';
import { ApplicationStats, ApplicationStatus, BOARD_STATUSES } from '../types';
import { Briefcase, FileCheck, CheckCircle2, XCircle, Clock, Plus } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: number;
  icon: LucideIcon;
  colorClass: string;
}

const StatCard = ({ title, value, icon: Icon, colorClass }: StatCardProps) => (
  <div className="bg-white dark:bg-zinc-900 rounded-xl p-5 shadow-sm border border-gray-100 dark:border-zinc-800 flex items-center">
    <div className={`p-3 rounded-lg ${colorClass} mr-4`}>
      <Icon className="w-6 h-6 text-white" />
    </div>
    <div>
      <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{title}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
    </div>
  </div>
);

const Dashboard = () => {
  const { notify } = useToast();
  // Only pipeline statuses. Fetching unfiltered returned the first 50 rows of
  // a backlog dominated by tens of thousands of UNAPPLIED listings, so the
  // board was usually empty regardless of how many live applications existed.
  const { applications, loading, error, updateStatus, refetch } = useApplications({
    status: BOARD_STATUSES,
    limit: 200,
    sort_by: 'updated_at',
  });
  const [stats, setStats] = useState<ApplicationStats | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const loadStats = useCallback(() => {
    api.getStats().then(setStats).catch(() => {
      notify('Could not load summary statistics.');
    });
  }, [notify]);

  useEffect(() => {
    loadStats();
  }, [loadStats, applications]);

  const handleStatusChange = async (id: string, newStatus: ApplicationStatus) => {
    try {
      await updateStatus(id, newStatus);
      loadStats();
    } catch (err) {
      // The board already rolled back; tell the user why without unmounting it.
      notify(err instanceof Error ? err.message : 'Could not update status.');
    }
  };

  const handleCreated = async () => {
    setAddOpen(false);
    await refetch();
    loadStats();
    notify('Application added.', 'success');
  };

  // The API's `total` counts every row, which is dominated by the scraped
  // UNAPPLIED backlog — reporting "15,159 applications" when one has actually
  // been applied to. Count only rows that have entered the pipeline.
  const appliedTotal = stats
    ? Object.entries(stats.by_status).reduce(
        (sum, [key, count]) =>
          key === ApplicationStatus.UNAPPLIED ? sum : sum + count,
        0,
      )
    : 0;

  if (loading && applications.length === 0) return <LoadingSpinner />;

  return (
    <div className="p-8 h-full flex flex-col">
      <div className="mb-8">
        <div className="flex items-start justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Overview</h1>
          <button
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
          >
            <Plus className="w-4 h-4 mr-2" />
            Add Application
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 text-sm text-red-800 dark:text-red-200">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard
            title="Total Applications"
            value={appliedTotal}
            icon={Briefcase}
            colorClass="bg-blue-500"
          />
          <StatCard
            title="Active Applications"
            value={stats?.applied ?? 0}
            icon={FileCheck}
            colorClass="bg-indigo-500"
          />
          <StatCard
            title="Interviews"
            value={stats?.interviews ?? 0}
            icon={Clock}
            colorClass="bg-amber-500"
          />
          <StatCard
            title="Offers"
            value={stats?.offers ?? 0}
            icon={CheckCircle2}
            colorClass="bg-green-500"
          />
          <StatCard
            title="Rejected"
            value={stats?.rejected ?? 0}
            icon={XCircle}
            colorClass="bg-red-500"
          />
        </div>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
          Application Pipeline
        </h2>
        <div className="flex-1 min-h-0">
          <KanbanBoard applications={applications} onStatusChange={handleStatusChange} />
        </div>
      </div>

      <AddApplicationDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={handleCreated}
      />
    </div>
  );
};

export default Dashboard;
