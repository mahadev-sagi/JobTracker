import React, { useMemo } from 'react';
import { 
  DndContext, 
  DragOverlay, 
  closestCorners, 
  KeyboardSensor, 
  PointerSensor, 
  useSensor, 
  useSensors,
  DragStartEvent,
  DragEndEvent,
  DragOverEvent
} from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { Application, ApplicationStatus, Column } from '../../types';
import KanbanColumn from './KanbanColumn';
import KanbanCard from './KanbanCard';

interface KanbanBoardProps {
  applications: Application[];
  onStatusChange: (id: string, newStatus: ApplicationStatus) => void;
}

const COLUMNS: Column[] = [
  { id: ApplicationStatus.APPLIED, title: 'Applied' },
  { id: ApplicationStatus.OA_RECEIVED, title: 'Online Assessment' },
  { id: ApplicationStatus.INTERVIEW_SCHEDULED, title: 'Interview' },
  { id: ApplicationStatus.OFFERED, title: 'Offer' },
  { id: ApplicationStatus.REJECTED, title: 'Rejected' },
];

const KanbanBoard: React.FC<KanbanBoardProps> = ({ applications, onStatusChange }) => {
  const [activeId, setActiveId] = React.useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragOver = (event: DragOverEvent) => {
    // For visual updates during drag if we were reordering within same column
    // Not strictly needed for simple status changes across columns
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);

    if (!over) return;

    const activeApp = applications.find(app => app.id === active.id);
    if (!activeApp) return;

    // Check if we dropped on a column or another card
    const overId = over.id as string;
    let newStatus: ApplicationStatus | null = null;
    
    // Check if overId is a column ID
    if (Object.values(ApplicationStatus).includes(overId as ApplicationStatus)) {
      newStatus = overId as ApplicationStatus;
    } else {
      // Over another card, find its status
      const overApp = applications.find(app => app.id === overId);
      if (overApp) {
        newStatus = overApp.status;
      }
    }

    if (newStatus && activeApp.status !== newStatus) {
      onStatusChange(activeApp.id, newStatus);
    }
  };

  const activeApplication = useMemo(
    () => applications.find(app => app.id === activeId),
    [activeId, applications]
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
    >
      <div className="flex gap-6 overflow-x-auto pb-4 h-full">
        {COLUMNS.map(column => (
          <KanbanColumn
            key={column.id}
            column={column}
            applications={applications.filter(app => app.status === column.id)}
          />
        ))}
      </div>
      
      <DragOverlay>
        {activeApplication ? <KanbanCard application={activeApplication} /> : null}
      </DragOverlay>
    </DndContext>
  );
};

export default KanbanBoard;
