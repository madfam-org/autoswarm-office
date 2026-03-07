'use client';

import { useEffect, useCallback } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';

interface PopupOverlayProps {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
}

/**
 * Text popup modal for 'popup' type interactables.
 * Shows centered overlay with title, content, and close button.
 */
export function PopupOverlay({ open, title, content, onClose }: PopupOverlayProps) {
  const trapRef = useFocusTrap<HTMLDivElement>(open);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === 'e' || e.key === 'E') {
        onClose();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/60"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        ref={trapRef}
        className="mx-4 max-w-lg rounded-lg border border-slate-700 bg-slate-800 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-3 text-sm font-bold text-indigo-400 font-mono">
          {title}
        </h2>
        <div className="mb-4 whitespace-pre-wrap text-xs leading-relaxed text-slate-300 font-mono">
          {content}
        </div>
        <button
          onClick={onClose}
          className="rounded bg-slate-700 px-4 py-1.5 text-xs text-slate-300 hover:bg-slate-600"
        >
          Close (ESC)
        </button>
      </div>
    </div>
  );
}
