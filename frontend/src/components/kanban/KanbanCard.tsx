import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Application } from '../../types';
import StatusBadge from '../common/StatusBadge';
import { ExternalLink, Calendar, Building2 } from 'lucide-react';

interface KanbanCardProps {
  application: Application;
}

const KanbanCard: React.FC<KanbanCardProps> = ({ application }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: application.id, data: application });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 100 : 'auto',
    opacity: isDragging ? 0.8 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={`bg-white dark:bg-zinc-900 p-4 rounded-lg shadow-sm border border-gray-200 dark:border-zinc-800 cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow ${
        isDragging ? 'shadow-lg ring-2 ring-blue-500' : ''
      }`}
    >
      <div className="flex justify-between items-start mb-2">
        <h4 className="font-medium text-gray-900 dark:text-gray-100 truncate pr-2">
          {application.role}
        </h4>
        {application.link && (
          <a
            href={application.link}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-400 hover:text-blue-500 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink className="w-4 h-4" />
          </a>
        )}
      </div>
      
      <div className="flex items-center text-sm text-gray-600 dark:text-gray-400 mb-3">
        <Building2 className="w-4 h-4 mr-1.5 flex-shrink-0" />
        <span className="truncate">{application.company}</span>
      </div>
      
      <div className="flex justify-between items-end mt-4">
        <div className="flex items-center text-xs text-gray-500 dark:text-gray-500">
          <Calendar className="w-3.5 h-3.5 mr-1" />
          {application.date_applied || application.date_posted || 'Unknown'}
        </div>
        <StatusBadge status={application.status} />
      </div>
    </div>
  );
};

export default KanbanCard;
