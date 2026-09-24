import clsx from 'clsx';
import { ApplicationStatus, STATUS_LABELS } from '../../types';

interface StatusBadgeProps {
  status: ApplicationStatus;
}

/**
 * Colour per status.
 *
 * Typed as a total Record, so adding a status to the enum without giving it a
 * colour is a build error rather than an `undefined` className at runtime.
 */
const statusColors: Record<ApplicationStatus, string> = {
  [ApplicationStatus.UNAPPLIED]:
    'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300 border-gray-200 dark:border-gray-700',
  [ApplicationStatus.APPLIED]:
    'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800',
  [ApplicationStatus.OA_RECEIVED]:
    'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 border-purple-200 dark:border-purple-800',
  [ApplicationStatus.INTERVIEW_SCHEDULED]:
    'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800',
  [ApplicationStatus.INTERVIEWED]:
    'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-800',
  [ApplicationStatus.OFFERED]:
    'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border-green-200 dark:border-green-800',
  [ApplicationStatus.ACCEPTED]:
    'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200 border-emerald-300 dark:border-emerald-700',
  [ApplicationStatus.REJECTED]:
    'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800',
  [ApplicationStatus.WITHDRAWN]:
    'bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300 border-slate-200 dark:border-slate-700',
  [ApplicationStatus.GHOSTED]:
    'bg-zinc-100 text-zinc-600 dark:bg-zinc-800/60 dark:text-zinc-400 border-zinc-200 dark:border-zinc-700',
};

const StatusBadge = ({ status }: StatusBadgeProps) => (
  <span
    className={clsx(
      'px-2.5 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap',
      statusColors[status],
    )}
  >
    {STATUS_LABELS[status] ?? status}
  </span>
);

export default StatusBadge;
