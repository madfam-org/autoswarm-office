'use client';

import { createContext, useContext, useCallback, useState } from 'react';

export type ToastSeverity = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  message: string;
  severity: ToastSeverity;
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

    // Auto-dismiss after 5s
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, addToast, removeToast };
}
