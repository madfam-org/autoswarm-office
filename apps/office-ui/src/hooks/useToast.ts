'use client';

import { createContext, useContext, useCallback, useState } from 'react';

export type ToastSeverity = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  message: string;
  severity: ToastSeverity;
  dismissing?: boolean;
}

export interface ToastContextValue {
  toasts: Toast[];
  addToast: (message: string, severity?: ToastSeverity) => void;
  removeToast: (id: string) => void;
}

export const ToastContext = createContext<ToastContextValue>({
  toasts: [],
  addToast: () => {},
  removeToast: () => {},
});

export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}

export function useToastState(): ToastContextValue {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, severity: ToastSeverity = 'info') => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev, { id, message, severity }]);

    // Auto-dismiss after 5s (with exit animation)
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => t.id === id ? { ...t, dismissing: true } : t));
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 200);
    }, 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    // Mark as dismissing for exit animation, then remove after delay
    setToasts((prev) => prev.map((t) => t.id === id ? { ...t, dismissing: true } : t));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 200);
  }, []);

  return { toasts, addToast, removeToast };
}
