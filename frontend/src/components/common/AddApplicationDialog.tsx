import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import * as api from '../../services/api';
import { ApplicationStatus, BOARD_STATUSES, STATUS_LABELS } from '../../types';
import { useToast } from './Toast';

interface AddApplicationDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const EMPTY = {
  company: '',
  role: '',
  location: '',
  url: '',
  notes: '',
  status: ApplicationStatus.APPLIED,
};

/**
 * Manual entry for an application the scraper never saw.
 *
 * POST /api/applications existed and worked but had no caller — there was no
 * way to record an application found anywhere other than the scraped feed.
 */
const AddApplicationDialog = ({ open, onClose, onCreated }: AddApplicationDialogProps) => {
  const { notify } = useToast();
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm(EMPTY);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const set = (key: keyof typeof EMPTY) => (value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.company.trim() || !form.role.trim()) {
      notify('Company and role are required.');
      return;
    }
    setSaving(true);
    try {
      await api.createApplication({
        company: form.company.trim(),
        role: form.role.trim(),
        location: form.location.trim() || undefined,
        url: form.url.trim() || undefined,
        notes: form.notes.trim() || undefined,
        source: 'MANUAL',
        status: form.status,
      });
      onCreated();
    } catch (err) {
      notify(api.errorMessage(err, 'Could not create application.'));
    } finally {
      setSaving(false);
    }
  };

  const field =
    'block w-full px-3 py-2 border border-gray-200 dark:border-zinc-700 rounded-lg bg-white dark:bg-zinc-900 text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
  const label = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1';

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add application"
        className="w-full max-w-lg bg-white dark:bg-zinc-900 rounded-xl shadow-xl border border-gray-200 dark:border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-zinc-800">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Add Application
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label} htmlFor="company">Company *</label>
              <input
                id="company"
                className={field}
                value={form.company}
                onChange={(e) => set('company')(e.target.value)}
                autoFocus
              />
            </div>
            <div>
              <label className={label} htmlFor="role">Role *</label>
              <input
                id="role"
                className={field}
                value={form.role}
                onChange={(e) => set('role')(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label} htmlFor="location">Location</label>
              <input
                id="location"
                className={field}
                value={form.location}
                onChange={(e) => set('location')(e.target.value)}
              />
            </div>
            <div>
              <label className={label} htmlFor="status">Status</label>
              <select
                id="status"
                className={field}
                value={form.status}
                onChange={(e) => set('status')(e.target.value)}
              >
                {[ApplicationStatus.UNAPPLIED, ...BOARD_STATUSES].map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className={label} htmlFor="url">Listing URL</label>
            <input
              id="url"
              className={field}
              value={form.url}
              onChange={(e) => set('url')(e.target.value)}
              placeholder="https://"
            />
          </div>

          <div>
            <label className={label} htmlFor="notes">Notes</label>
            <textarea
              id="notes"
              rows={3}
              className={field}
              value={form.notes}
              onChange={(e) => set('notes')(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium rounded-md border border-gray-200 dark:border-zinc-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-zinc-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving…' : 'Add Application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddApplicationDialog;
