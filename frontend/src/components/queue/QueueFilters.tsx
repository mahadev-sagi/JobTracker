import React from 'react';
import { Search } from 'lucide-react';

interface QueueFiltersProps {
  searchTerm: string;
  onSearchChange: (value: string) => void;
}

const QueueFilters: React.FC<QueueFiltersProps> = ({ searchTerm, onSearchChange }) => {
  return (
    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
      <div className="relative w-full sm:w-96">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <Search className="h-5 w-5 text-gray-400" />
        </div>
        <input
          type="text"
          placeholder="Search company or role..."
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          className="block w-full pl-10 pr-3 py-2 border border-gray-200 dark:border-zinc-700 rounded-lg leading-5 bg-white dark:bg-zinc-900 text-gray-900 dark:text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 sm:text-sm transition-colors"
        />
      </div>
      
      <div className="flex gap-2">
        {/* Placeholder for future filters like Date Range or Source */}
      </div>
    </div>
  );
};

export default QueueFilters;
