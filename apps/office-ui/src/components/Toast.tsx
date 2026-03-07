'use client';

import { type ReactNode } from 'react';
import { ToastContext, useToastState, type Toast as ToastType } from '@/hooks/useToast';

const SEVERITY_STYLES: Record<ToastType['severity'], string> = {
  success: 'border-emerald-500 bg-emerald-900/90 text-emerald-200',
  error: 'border-red-500 bg-red-900/90 text-red-200',
  warning: 'border-amber-500 bg-amber-900/90 text-amber-200',
  info: 'border-indigo-500 bg-indigo-900/90 text-indigo-200',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const value = useToastState();

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={value.toasts} onRemove={value.removeToast} />
    </ToastContext.Provider>
  );
}

function ToastContainer({
  toasts,
  onRemove,
}: {
  toasts: ToastType[];
  onRemove: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[60] flex flex-col gap-2 pointer-events-none" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto flex items-center gap-2 rounded border px-4 py-2 font-mono text-xs shadow-lg backdrop-blur-sm animate-in slide-in-from-right ${SEVERITY_STYLES[toast.severity]}`}
          role="alert"
        >
          <span className="flex-1">{toast.message}</span>
          <button
            onClick={() => onRemove(toast.id)}
            className="ml-2 opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            x
          </button>
        </div>
      ))}
    </div>
  );
}
