import React from 'react';
import { ApplicationStatus } from '../../types';
import clsx from 'clsx';

interface StatusBadgeProps {
  status: ApplicationStatus;
}

const statusColors: Record<ApplicationStatus, string> = {
  [ApplicationStatus.UNAPPLIED]: 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300 border-gray-200 dark:border-gray-700',
  [ApplicationStatus.APPLIED]: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800',
  [ApplicationStatus.OA_RECEIVED]: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 border-purple-200 dark:border-purple-800',
  [ApplicationStatus.INTERVIEW_SCHEDULED]: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800',
  [ApplicationStatus.OFFERED]: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border-green-200 dark:border-green-800',
  [ApplicationStatus.REJECTED]: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800',
};

const formatStatusText = (status: string) => {
  return status.replace(/_/g, ' ');
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  return (
    <span className={clsx(
      'px-2.5 py-0.5 rounded-full text-xs font-medium border',
      statusColors[status]
    )}>
      {formatStatusText(status)}
    </span>
  );
};

export default StatusBadge;
