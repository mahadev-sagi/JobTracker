import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Mail, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/common/Toast';
import * as api from '../services/api';
import { EmailActivity, STATUS_LABELS } from '../types';

/** Results the Gmail OAuth callback redirects back with, as ?gmail=... */
const CONNECT_RESULTS: Record<string, [string, 'success' | 'error']> = {
  connected: ['Gmail connected. New application emails will update your board.', 'success'],
  connected_no_push: [
    'Gmail connected, but this server has no Pub/Sub topic configured, so updates will not arrive yet.',
    'error',
  ],
  cancelled: ['Gmail connection was cancelled.', 'error'],
  scope_missing: [
    'Gmail was not connected: the "read your email" permission was unticked on Google\'s screen.',
    'error',
  ],
  in_use: ['That Gmail account is already connected to another JobTracker user.', 'error'],
  watch_failed: [
    'Gmail connected, but notifications could not be started. They will be retried automatically.',
    'error',
  ],
  error: ['Gmail connection failed. Please try again.', 'error'],
};

const OUTCOME_TEXT: Record<EmailActivity['outcome'], string> = {
  updated: 'Updated',
  unchanged: 'No change',
  created: 'Added',
  ambiguous: 'Needs you',
};

const formatTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

const card =
  'bg-white dark:bg-zinc-900 rounded-xl border border-gray-200 dark:border-zinc-800 p-6';

const Settings = () => {
  const { user, refresh } = useAuth();
  const { notify } = useToast();
  const [params, setParams] = useSearchParams();
  const [activity, setActivity] = useState<EmailActivity[]>([]);
  const [disconnecting, setDisconnecting] = useState(false);

  const loadActivity = useCallback(() => {
    api.getEmailActivity().then(setActivity).catch(() => setActivity([]));
  }, []);

  useEffect(() => {
    const result = params.get('gmail');
    if (!result) return;
    const [message, kind] = CONNECT_RESULTS[result] ?? CONNECT_RESULTS.error;
    notify(message, kind);
    refresh();
    setParams({}, { replace: true });
  }, [params, setParams, notify, refresh]);

  useEffect(() => {
    if (user?.gmail) loadActivity();
  }, [user?.gmail, loadActivity]);

  if (!user) return null;
  const gmail = user.gmail;

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await api.disconnectGmail();
      await refresh();
      setActivity([]);
      notify('Gmail disconnected and access revoked.', 'success');
    } catch (err) {
      notify(api.errorMessage(err, 'Could not disconnect Gmail.'));
    } finally {
      setDisconnecting(false);
    }
  };

  const connectButton = (label: string) => (
    <a
      href={api.GMAIL_CONNECT_URL}
      className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 transition-colors"
    >
      <Mail className="w-4 h-4 mr-2" />
      {label}
    </a>
  );

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>

      <section className={card}>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">Gmail</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-5">
          JobTracker reads new mail in your inbox (read-only) and uses AI to spot rejections,
          interview invites, assessments and offers, then updates the matching application.
          Other mail is skipped and nothing from it is stored.
        </p>

        {!user.gmail_available && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Gmail connection is not configured on this server yet.
          </p>
        )}

        {user.gmail_available && !gmail && connectButton('Connect Gmail')}

        {gmail?.status === 'revoked' && (
          <div className="space-y-4">
            <div className="flex items-start text-sm text-amber-700 dark:text-amber-400">
              <AlertTriangle className="w-5 h-5 mr-2 shrink-0" />
              Access to {gmail.email_address} has expired or was revoked. Reconnect to resume
              automatic updates.
            </div>
            <div className="flex gap-3">
              {connectButton('Reconnect Gmail')}
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-zinc-800 disabled:opacity-50"
              >
                Remove
              </button>
            </div>
          </div>
        )}

        {gmail?.status === 'active' && (
          <div className="space-y-4">
            <div className="flex items-start text-sm text-gray-800 dark:text-gray-200">
              <CheckCircle2 className="w-5 h-5 mr-2 shrink-0 text-green-600" />
              <div>
                Connected to <span className="font-medium">{gmail.email_address}</span>
                <div className="text-gray-500 dark:text-gray-400">
                  Last checked {formatTime(gmail.last_synced_at)}
                  {!gmail.watch_expires_at && ' · notifications not active yet'}
                </div>
                {gmail.last_error && (
                  <div className="text-amber-700 dark:text-amber-400">{gmail.last_error}</div>
                )}
              </div>
            </div>
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              className="px-4 py-2 text-sm font-medium rounded-md border border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              {disconnecting ? 'Disconnecting…' : 'Disconnect Gmail'}
            </button>
          </div>
        )}
      </section>

      {gmail && (
        <section className={card}>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
            Recent email activity
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            "Needs you" means an email could belong to more than one of your applications at
            that company, so nothing was changed. Update the right one by hand.
          </p>
          {activity.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">No application emails yet.</p>
          ) : (
            <ul className="divide-y divide-gray-100 dark:divide-zinc-800">
              {activity.map((item) => (
                <li key={item.message_id} className="py-3 flex items-start justify-between gap-4 text-sm">
                  <div className="min-w-0">
                    <div className="font-medium text-gray-900 dark:text-gray-100 truncate">
                      {item.company}
                      {item.role ? ` · ${item.role}` : ''}
                    </div>
                    <div className="text-gray-500 dark:text-gray-400 truncate">{item.subject}</div>
                  </div>
                  <div className="text-right shrink-0">
                    <div
                      className={
                        item.outcome === 'ambiguous'
                          ? 'text-amber-700 dark:text-amber-400 font-medium'
                          : 'text-gray-700 dark:text-gray-300'
                      }
                    >
                      {OUTCOME_TEXT[item.outcome]}
                      {item.status && item.outcome !== 'ambiguous' ? ` → ${STATUS_LABELS[item.status]}` : ''}
                    </div>
                    <div className="text-xs text-gray-400">{formatTime(item.processed_at)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
};

export default Settings;
