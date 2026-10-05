import { NavLink } from 'react-router-dom';
import { LayoutDashboard, ListTodo, Briefcase, Settings, LogOut, MailWarning } from 'lucide-react';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { useAuth } from '../../auth/AuthContext';

const NavItem = ({ to, icon: Icon, label, badge }: { to: string; icon: LucideIcon; label: string; badge?: boolean }) => (
  <NavLink
    to={to}
    end={to === '/'}
    className={({ isActive }) => clsx(
      'flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors',
      isActive
        ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
        : 'text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-zinc-800/50'
    )}
  >
    <Icon className="w-5 h-5 mr-3" />
    {label}
    {badge && <MailWarning className="w-4 h-4 ml-auto text-amber-500" aria-label="Needs attention" />}
  </NavLink>
);

const Sidebar = () => {
  const { user, signOut } = useAuth();
  // Flag Settings when Gmail needs reconnecting, so a silently stalled inbox
  // does not go unnoticed.
  const gmailNeedsAttention = user?.gmail?.status === 'revoked';

  return (
    <div className="w-64 bg-white dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 flex flex-col">
      <div className="h-16 flex items-center px-6 border-b border-gray-200 dark:border-zinc-800">
        <Briefcase className="w-6 h-6 text-blue-600 dark:text-blue-500 mr-2" />
        <span className="text-lg font-bold text-gray-900 dark:text-white">JobTracker</span>
      </div>

      <nav className="flex-1 px-4 py-4 space-y-1">
        <NavItem to="/" icon={LayoutDashboard} label="Dashboard" />
        <NavItem to="/queue" icon={ListTodo} label="Queue" />
        <NavItem to="/settings" icon={Settings} label="Settings" badge={gmailNeedsAttention} />
      </nav>

      {user && (
        <div className="px-4 py-4 border-t border-gray-200 dark:border-zinc-800 flex items-center gap-3">
          {user.picture_url ? (
            <img src={user.picture_url} alt="" referrerPolicy="no-referrer" className="w-8 h-8 rounded-full" />
          ) : (
            <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 flex items-center justify-center text-sm font-semibold">
              {(user.name || user.email).charAt(0).toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
              {user.name || user.email}
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{user.email}</div>
          </div>
          <button
            onClick={signOut}
            title="Sign out"
            aria-label="Sign out"
            className="p-1.5 rounded-md text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:hover:text-gray-200 dark:hover:bg-zinc-800"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
};

export default Sidebar;
