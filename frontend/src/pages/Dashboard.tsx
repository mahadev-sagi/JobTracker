import { useEffect, useState } from 'react';
import KanbanBoard from '../components/kanban/KanbanBoard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useApplications } from '../hooks/useApplications';
import * as api from '../services/api';
import { ApplicationStats } from '../types';
import { Briefcase, FileCheck, CheckCircle2, XCircle, Clock } from 'lucide-react';
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
  const { applications, loading, error, updateStatus } = useApplications();
  const [stats, setStats] = useState<ApplicationStats | null>(null);

  useEffect(() => {
    api.getStats().then(setStats).catch(console.error);
  }, [applications]); // Refetch stats when applications change

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="p-8 text-red-500">Error: {error}</div>;

  return (
    <div className="p-8 h-full flex flex-col">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-6">Overview</h1>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard 
            title="Total Applications" 
            value={stats?.total || 0} 
            icon={Briefcase} 
            colorClass="bg-blue-500" 
          />
          <StatCard 
            title="Active Applications" 
            value={stats?.applied || 0} 
            icon={FileCheck} 
            colorClass="bg-indigo-500" 
          />
          <StatCard 
            title="Interviews" 
            value={stats?.interviews || 0} 
            icon={Clock} 
            colorClass="bg-amber-500" 
          />
          <StatCard 
            title="Offers" 
            value={stats?.offers || 0} 
            icon={CheckCircle2} 
            colorClass="bg-green-500" 
          />
          <StatCard 
            title="Rejected" 
            value={stats?.rejected || 0} 
            icon={XCircle} 
            colorClass="bg-red-500" 
          />
        </div>
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">Application Pipeline</h2>
        <div className="flex-1 min-h-0">
          <KanbanBoard 
            applications={applications} 
            onStatusChange={updateStatus} 
          />
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
