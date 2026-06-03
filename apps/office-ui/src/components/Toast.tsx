'use client';

import { type ReactNode } from 'react';
import { CloseButton } from '@selva/ui';
import { ToastContext, useToastState, type Toast as ToastType } from '@/hooks/useToast';
import { useDemoMode } from '@/hooks/useDemoMode';

const SEVERITY_STYLES: Record<ToastType['severity'], string> = {
  success: 'border-emerald-500 bg-emerald-900/90 text-emerald-200',
  error: 'border-red-500 bg-red-900/90 text-red-200',
  warning: 'border-amber-500 bg-amber-900/90 text-amber-200',
  info: 'border-indigo-500 bg-indigo-900/90 text-indigo-200',
};

const SEVERITY_ICONS: Record<ToastType['severity'], { symbol: string; color: string }> = {
  success: { symbol: '\u2713', color: 'text-emerald-400' },
  error: { symbol: '\u2717', color: 'text-red-400' },
  warning: { symbol: '\u26A0', color: 'text-amber-400' },
  info: { symbol: '\u24D8', color: 'text-indigo-400' },
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
  // DemoBanner sits at top:0 with z-banner; without offset the Toast container
  // (top-4 + z-toast) renders behind the banner and is invisible in demo mode.
  // The banner is roughly 28px tall (py-1.5 + 9px text); top-12 (48px) clears it
  // with breathing room on both desktop and mobile (banner does not change
  // height between breakpoints — content wraps within the same row).
  const { isDemo } = useDemoMode();
  if (toasts.length === 0) return null;

  return (
    <div
      className={`fixed right-4 ${isDemo ? 'top-12' : 'top-4'} z-toast flex flex-col gap-2 pointer-events-none`}
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto flex items-center gap-2 border px-4 py-2 font-mono text-xs shadow-lg backdrop-blur-sm pixel-border ${toast.dismissing ? 'animate-slide-out-right' : 'animate-slide-in-right'} ${SEVERITY_STYLES[toast.severity]}`}
          role="alert"
        >
          <span className={`font-bold ${SEVERITY_ICONS[toast.severity].color}`} aria-hidden="true">
            {SEVERITY_ICONS[toast.severity].symbol}
          </span>
          <span className="flex-1">{toast.message}</span>
          <CloseButton
            onClick={() => onRemove(toast.id)}
            label="Dismiss"
            className="ml-2 opacity-60 hover:opacity-100"
          />
        </div>
      ))}
    </div>
  );
}
