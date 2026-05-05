'use client';

import { useEffect, useRef, useState } from 'react';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { buildPortalUrl, emitJumanjiEvent, JUMANJI_EVENTS } from './jumanjiAnalytics';

interface JumanjiPortalModalProps {
  open: boolean;
  onClose: () => void;
  userId?: string | null;
  orgId?: string | null;
  /** ms-since-load when the user activated the portal (for analytics). */
  discoveredAt: number;
  currentPage: string;
}

/**
 * The "step in" experience. Iframes play.rondel.io when possible
 * (verified iframe-friendly headers as of 2026-05-04 — see PR body
 * for the curl trace). If the iframe fails to load (CSP added later,
 * network error, sandbox refusal), we surface a "Open in new tab"
 * fallback button that uses target="_blank" rel="noopener".
 */
export function JumanjiPortalModal({
  open,
  onClose,
  userId,
  orgId,
  discoveredAt,
  currentPage,
}: JumanjiPortalModalProps) {
  const trapRef = useFocusTrap(open);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [iframeFailed, setIframeFailed] = useState(false);

  const portalUrl = buildPortalUrl({ userId, orgId });

  useEffect(() => {
    if (!open) return;
    emitJumanjiEvent(JUMANJI_EVENTS.PORTALED, {
      user_id: userId,
      org_id: orgId,
      discovered_at: discoveredAt,
      current_page: currentPage,
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, userId, orgId, discoveredAt, currentPage]);

  // Detect iframe loading failures via a 6s timer — sandboxed iframes
  // don't reliably fire `error` events.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      try {
        const doc = iframeRef.current?.contentDocument;
        // contentDocument === null when the cross-origin frame loaded fine.
        // We only flag failure if BOTH the doc is accessible AND empty,
        // which is the symptom of a frame-busting refusal.
        if (doc && doc.body && doc.body.children.length === 0) {
          setIframeFailed(true);
        }
      } catch {
        // SecurityError = cross-origin loaded successfully. Good.
      }
    }, 6000);
    return () => clearTimeout(t);
  }, [open]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="jumanji-portal-title"
      className="fixed inset-0 z-modal flex items-center justify-center bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={trapRef as React.RefObject<HTMLDivElement>}
        className="relative h-[80vh] w-[90vw] max-w-5xl overflow-hidden rounded-md border-2 border-emerald-700/70 bg-[#0e1f15] shadow-[0_0_60px_rgba(95,196,138,0.35)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-emerald-900/60 bg-[#0a1810] px-4 py-2">
          <h2
            id="jumanji-portal-title"
            className="pixel-text text-xs uppercase tracking-widest text-emerald-300"
          >
            The dice opened a way · play.rondel.io
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close portal"
            className="rounded-sm px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-900/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            ✕
          </button>
        </div>

        {iframeFailed ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
            <p className="text-sm text-emerald-200">
              The portal would not open here. Step through in a new tab instead.
            </p>
            <a
              href={portalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-sm border border-emerald-500 bg-emerald-700/30 px-4 py-2 text-xs uppercase tracking-wider text-emerald-200 hover:bg-emerald-700/50"
            >
              Open play.rondel.io
            </a>
          </div>
        ) : (
          <iframe
            ref={iframeRef}
            src={portalUrl}
            title="Rondelio simulator"
            className="h-[calc(100%-2.5rem)] w-full bg-black"
            sandbox="allow-scripts allow-forms allow-popups allow-same-origin"
            referrerPolicy="strict-origin-when-cross-origin"
            // data-suggestion="audio-v2" — when sound design lands,
            // pipe an ambient-jungle loop here scoped to the iframe lifecycle.
            data-suggestion="audio-v2"
          />
        )}
      </div>
    </div>
  );
}
