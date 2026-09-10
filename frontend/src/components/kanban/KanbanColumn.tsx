import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { Application, Column } from '../../types';
import KanbanCard from './KanbanCard';

interface KanbanColumnProps {
  column: Column;
  applications: Application[];
}

const KanbanColumn: React.FC<KanbanColumnProps> = ({ column, applications }) => {
  const { setNodeRef, isOver } = useDroppable({
    id: column.id,
  });

  return (
    <div className="flex flex-col w-80 shrink-0">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold text-gray-700 dark:text-gray-300">
          {column.title}
        </h3>
        <span className="bg-gray-200 dark:bg-zinc-800 text-gray-600 dark:text-gray-400 text-xs font-medium px-2 py-1 rounded-full">
          {applications.length}
        </span>
      </div>
      
      <div
        ref={setNodeRef}
        className={`flex-1 bg-gray-100 dark:bg-zinc-950 rounded-xl p-3 flex flex-col gap-3 min-h-[500px] transition-colors ${
          isOver ? 'bg-gray-200 dark:bg-zinc-900' : ''
        }`}
      >
        <SortableContext 
          items={applications.map(app => app.id)} 
          strategy={verticalListSortingStrategy}
        >
          {applications.map((app) => (
            <KanbanCard key={app.id} application={app} />
          ))}
        </SortableContext>
        
        {applications.length === 0 && (
          <div className="h-full flex items-center justify-center text-sm text-gray-400 dark:text-zinc-600 border-2 border-dashed border-gray-200 dark:border-zinc-800 rounded-lg">
            Drop here
          </div>
        )}
      </div>
    </div>
  );
};

export default KanbanColumn;
