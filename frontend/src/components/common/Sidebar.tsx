import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, ListTodo, Briefcase } from 'lucide-react';
import clsx from 'clsx';

const Sidebar = () => {
  return (
    <div className="w-64 bg-white dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 flex flex-col">
      <div className="h-16 flex items-center px-6 border-b border-gray-200 dark:border-zinc-800">
        <Briefcase className="w-6 h-6 text-blue-600 dark:text-blue-500 mr-2" />
        <span className="text-lg font-bold text-gray-900 dark:text-white">JobTracker</span>
      </div>
      
      <nav className="flex-1 px-4 py-4 space-y-1">
        <NavLink
          to="/"
          className={({ isActive }) => clsx(
            'flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors',
            isActive 
              ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400' 
              : 'text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-zinc-800/50'
          )}
        >
          <LayoutDashboard className="w-5 h-5 mr-3" />
          Dashboard
        </NavLink>
        
        <NavLink
          to="/queue"
          className={({ isActive }) => clsx(
            'flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors',
            isActive 
              ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400' 
              : 'text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-zinc-800/50'
          )}
        >
          <ListTodo className="w-5 h-5 mr-3" />
          Queue
        </NavLink>
      </nav>
    </div>
  );
};

export default Sidebar;
