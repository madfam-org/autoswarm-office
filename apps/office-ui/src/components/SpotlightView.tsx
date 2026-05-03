'use client';

import { useRef, useEffect, useState, type FC } from 'react';
import type { ProximityPeer } from '@/hooks/useProximityVideo';
import { useFocusTrap } from '@/hooks/useFocusTrap';

interface SpotlightViewProps {
  /** Whether spotlight is active */
  active: boolean;
  /** Whether the local player is the presenter (don't show view to presenter) */
  isPresenting: boolean;
  /** Name of the current presenter */
  presenterName: string | null;
  /** Session ID of the current presenter */
  presenterSessionId: string | null;
  /** All proximity peers with their streams */
  peers: ProximityPeer[];
  /** Callback to close/minimize the spotlight view */
  onClose: () => void;
}

/**
 * Large video panel (80vh) that shows the spotlight presenter's stream
 * to all audience members. Only visible when someone else is presenting.
 */
export const SpotlightView: FC<SpotlightViewProps> = ({
  active,
  isPresenting,
  presenterName,
  presenterSessionId,
  peers,
  onClose,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [minimized, setMinimized] = useState(false);

  // Find the presenter's stream from peers
  const presenterPeer = presenterSessionId
    ? peers.find((p) => p.sessionId === presenterSessionId)
    : null;
  const presenterStream = presenterPeer?.stream ?? null;

  // Attach stream to video element
  useEffect(() => {
    if (videoRef.current && presenterStream) {
      videoRef.current.srcObject = presenterStream;
    }
  }, [presenterStream]);

  // Reset minimized state when spotlight stops
  useEffect(() => {
    if (!active) {
      setMinimized(false);
    }
  }, [active]);

  // Compute visibility before any hook call that depends on it
  const visible = active && !isPresenting && !minimized;

  // ESC closes (or minimizes) the spotlight view for keyboard users
  useEffect(() => {
    if (!visible) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [visible, onClose]);

  const focusTrapRef = useFocusTrap<HTMLDivElement>(visible);

  if (!visible) return null;

  return (
    <div
      ref={focusTrapRef}
      className="absolute inset-0 z-modal flex items-center justify-center bg-black/70 animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="spotlight-presenter-name"
    >
      <div className="relative flex flex-col items-center gap-3">
        {/* Header bar */}
        <div className="flex w-full items-center justify-between px-2">
          <span
            id="spotlight-presenter-name"
            className="flex items-center gap-2 text-xs font-mono text-violet-400"
          >
            <span className="inline-block h-2 w-2 rounded-full bg-violet-400 animate-pulse" />
            {presenterName ?? 'Someone'} is presenting
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setMinimized(true)}
              className="rounded px-2 py-1 text-xs font-mono bg-slate-700/80 text-slate-400 hover:bg-slate-600 transition-colors"
              aria-label="Minimize spotlight"
            >
              Minimize
            </button>
            <button
              onClick={onClose}
              className="rounded px-2 py-1 text-xs font-mono bg-slate-700/80 text-slate-400 hover:bg-slate-600 transition-colors"
              aria-label="Close spotlight view"
            >
              Close
            </button>
          </div>
        </div>

        {/* Video container */}
        <div
          className="overflow-hidden rounded-lg border-2 border-violet-500/50 bg-slate-900"
          style={{ maxHeight: '80vh', maxWidth: '90vw' }}
        >
          {presenterStream ? (
            <video
              ref={videoRef}
              autoPlay
              playsInline
              className="h-full w-full object-contain"
              style={{ maxHeight: '80vh', maxWidth: '90vw' }}
            />
          ) : (
            <div className="flex h-64 w-96 items-center justify-center text-slate-500 font-mono text-xs">
              Waiting for presenter stream...
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
