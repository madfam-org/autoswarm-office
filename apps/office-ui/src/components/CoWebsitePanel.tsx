'use client';

import { useState, useEffect, useCallback } from 'react';

interface CoWebsitePanelProps {
  url: string | null;
  title: string;
  onClose: () => void;
}

/**
 * Sliding iframe panel that opens when a player interacts with a 'url' or
 * 'jitsi-zone' interactable. Slides in from the right side of the screen.
 */
export function CoWebsitePanel({ url, title, onClose }: CoWebsitePanelProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (url) {
      // Delay slightly for slide animation
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [url]);

  const handleClose = useCallback(() => {
    setVisible(false);
    // Wait for slide-out animation before unmounting
    setTimeout(onClose, 300);
  }, [onClose]);

  // Handle Escape key to close
  useEffect(() => {
    if (!url) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [url, handleClose]);

  if (!url) return null;

  return (
    <div
      className={`fixed top-0 right-0 z-50 flex h-full flex-col bg-slate-900 border-l border-slate-700 shadow-2xl transition-transform duration-300 ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
      style={{ width: 'min(50vw, 640px)' }}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800 px-4 py-2">
        <span className="truncate text-xs text-slate-300 font-mono">
          {title}
        </span>
        <button
          onClick={handleClose}
          className="ml-2 rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-200"
          aria-label="Close panel"
        >
          ESC
        </button>
      </div>

      {/* Iframe content */}
      <iframe
        src={url}
        title={title}
        className="flex-1 border-0 bg-white"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        allow="camera; microphone; display-capture"
      />
    </div>
  );
}
