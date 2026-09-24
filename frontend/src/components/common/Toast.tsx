import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, CheckCircle2, X } from 'lucide-react';

type ToastKind = 'error' | 'success';

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  notify: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastContextValue>({ notify: () => undefined });

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastContext);

const AUTO_DISMISS_MS = 5000;

const ToastItem = ({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) => {
  useEffect(() => {
    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const isError = toast.kind === 'error';
  const Icon = isError ? AlertCircle : CheckCircle2;

  return (
    <div
      role="status"
      className={`flex items-start gap-3 w-80 p-3 rounded-lg shadow-lg border text-sm ${
        isError
          ? 'bg-red-50 dark:bg-red-950/60 border-red-200 dark:border-red-900 text-red-800 dark:text-red-200'
          : 'bg-green-50 dark:bg-green-950/60 border-green-200 dark:border-green-900 text-green-800 dark:text-green-200'
      }`}
    >
      <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <span className="flex-1">{toast.message}</span>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        className="opacity-60 hover:opacity-100 transition-opacity"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};

/**
 * Transient notifications.
 *
 * A failed action — most often the API refusing a status transition the state
 * machine disallows — needs to be visible without unmounting the view the
 * user is working in.
 */
export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((message: string, kind: ToastKind = 'error') => {
    setToasts((prev) => [...prev, { id: Date.now() + Math.random(), kind, message }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
};
