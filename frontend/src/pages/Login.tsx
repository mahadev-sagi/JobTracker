import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Briefcase } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import * as api from '../services/api';
import { AuthConfig } from '../types';

/** Messages for the ?error= codes the backend's OAuth callback redirects with. */
const ERRORS: Record<string, string> = {
  cancelled: 'Sign-in was cancelled.',
  not_invited:
    "This Google account hasn't been invited yet. Ask the person who runs this JobTracker to add you.",
  state: 'Sign-in expired or was started in another tab. Please try again.',
  google: 'Google sign-in failed. Please try again.',
  account_conflict:
    'This email is linked to a different Google account here. Ask the person who runs this JobTracker for help.',
};

const Login = () => {
  const { refresh } = useAuth();
  const [params] = useSearchParams();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [devEmail, setDevEmail] = useState('');
  const [devError, setDevError] = useState<string | null>(null);

  useEffect(() => {
    api.getAuthConfig().then(setConfig).catch(() => setConfig({ google: false, dev_login: false }));
  }, []);

  const error = params.get('error');

  const submitDevLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.devLogin(devEmail.trim());
      await refresh();
    } catch (err) {
      setDevError(api.errorMessage(err, 'Development sign-in failed.'));
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-zinc-950 px-4">
      <div className="w-full max-w-sm bg-white dark:bg-zinc-900 rounded-xl border border-gray-200 dark:border-zinc-800 shadow-sm p-8">
        <div className="flex items-center mb-6">
          <Briefcase className="w-7 h-7 text-blue-600 dark:text-blue-500 mr-2" />
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">JobTracker</h1>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
          Track your job applications. Connect Gmail and status updates from recruiters are
          applied automatically.
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/40 text-sm text-red-800 dark:text-red-200">
            {ERRORS[error] ?? 'Sign-in failed. Please try again.'}
          </div>
        )}

        {config?.google !== false && (
          <a
            href={api.GOOGLE_SIGN_IN_URL}
            className="flex w-full items-center justify-center px-4 py-2.5 text-sm font-medium rounded-md border border-gray-300 dark:border-zinc-700 text-gray-800 dark:text-gray-100 bg-white dark:bg-zinc-800 hover:bg-gray-50 dark:hover:bg-zinc-700 transition-colors"
          >
            Sign in with Google
          </a>
        )}
        {config?.google === false && !config.dev_login && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Sign-in is not configured on this server yet.
          </p>
        )}

        {config?.dev_login && (
          <form onSubmit={submitDevLogin} className="mt-6 pt-6 border-t border-gray-200 dark:border-zinc-800">
            <label htmlFor="dev-email" className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
              Development sign-in (no Google)
            </label>
            <div className="flex gap-2">
              <input
                id="dev-email"
                type="email"
                required
                value={devEmail}
                onChange={(e) => setDevEmail(e.target.value)}
                placeholder="you@example.com"
                className="flex-1 min-w-0 px-3 py-2 border border-gray-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900 text-sm text-gray-900 dark:text-gray-100"
              />
              <button
                type="submit"
                className="px-3 py-2 text-sm font-medium rounded-md text-white bg-gray-700 hover:bg-gray-800"
              >
                Go
              </button>
            </div>
            {devError && <p className="mt-2 text-xs text-red-600">{devError}</p>}
          </form>
        )}
      </div>
    </div>
  );
};

export default Login;
