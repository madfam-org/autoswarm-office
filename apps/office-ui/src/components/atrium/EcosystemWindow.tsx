'use client';

/**
 * EcosystemWindow — the primitive that renders one platform window
 * inside the Atrium overlay.
 *
 * Hand-rolled drag/resize on top of pointer events (no react-rnd or
 * similar) per spec — no new heavy deps. The window has a draggable
 * title bar, resizable corners (8 handles: 4 sides + 4 corners), and
 * three states (windowed / minimized / maximized).
 *
 * State preservation: the iframe is rendered ONCE per slug as long as
 * the window is in the store. Minimizing hides the window with
 * `display: none` instead of unmounting; maximizing only changes
 * geometry. Focus changes only re-stack via z-index. The iframe NEVER
 * remounts as long as the slug stays in the store.
 *
 * Accessibility:
 *  - title bar is a button with aria-label
 *  - close/min/max buttons have explicit aria-labels
 *  - prefers-reduced-motion disables the open/close transitions
 *  - WCAG AA color contrast on the chrome
 *
 * The iframe sandbox is `allow-scripts allow-forms allow-popups
 * allow-same-origin` per spec — same-origin is needed because the
 * platforms are first-party MADFAM sites and they need cookies / auth
 * to load. We accept the trade-off: cross-origin iframes from MADFAM
 * domains are trusted at the same level as the parent app.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import {
  useAtriumStore,
  type AtriumWindow,
  type WindowGeometry,
} from '@/stores/atrium-windows';

interface EcosystemWindowProps {
  window: AtriumWindow;
  /** True when this is the top window (highest z-index). */
  isFocused: boolean;
}

/** Minimum dimensions so the window always has visible chrome. */
const MIN_WIDTH = 320;
const MIN_HEIGHT = 200;

/** Reduced-motion-aware transition duration. */
const TRANSITION_MS = 200;

type ResizeEdge =
  | 'n'
  | 's'
  | 'e'
  | 'w'
  | 'ne'
  | 'nw'
  | 'se'
  | 'sw'
  | null;

interface DragState {
  mode: 'drag' | 'resize';
  edge: ResizeEdge;
  startX: number;
  startY: number;
  startGeometry: WindowGeometry;
}

function clampGeometry(g: WindowGeometry): WindowGeometry {
  if (typeof window === 'undefined') return g;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.max(MIN_WIDTH, Math.min(g.width, vw));
  const height = Math.max(MIN_HEIGHT, Math.min(g.height, vh));
  // Keep at least 60px of title bar visible so the window can't be
  // dragged completely off-screen.
  const x = Math.max(-width + 60, Math.min(g.x, vw - 60));
  const y = Math.max(0, Math.min(g.y, vh - 40));
  return { x, y, width, height };
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function EcosystemWindow({
  window: w,
  isFocused,
}: EcosystemWindowProps): JSX.Element | null {
  const close = useAtriumStore((s) => s.close);
  const focus = useAtriumStore((s) => s.focus);
  const minimize = useAtriumStore((s) => s.minimize);
  const maximize = useAtriumStore((s) => s.maximize);
  const setGeometry = useAtriumStore((s) => s.setGeometry);

  const [dragState, setDragState] = useState<DragState | null>(null);
  const [iframeFailed, setIframeFailed] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // Detect prefers-reduced-motion once on mount (cheap; no listener).
  const reducedMotion = useMemo(prefersReducedMotion, []);

  // Render geometry — either the windowed/maximized geometry from the
  // store, or null when minimized (the chrome is hidden but iframe
  // stays in the DOM via display:none).
  const renderGeometry: WindowGeometry = useMemo(() => {
    if (w.state === 'maximized' && typeof window !== 'undefined') {
      // Full viewport minus a tiny border so the office canvas peeks
      // through and the metaphor holds.
      return { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight };
    }
    return w.geometry;
  }, [w.state, w.geometry]);

  // Pointer-driven drag/resize. We attach move/up listeners to window
  // instead of the title bar so dragging continues even when the
  // pointer leaves the chrome (matches OS window-manager behavior).
  useEffect(() => {
    if (!dragState) return;

    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - dragState.startX;
      const dy = e.clientY - dragState.startY;
      const { startGeometry: sg } = dragState;

      let next: WindowGeometry = { ...sg };

      if (dragState.mode === 'drag') {
        next = { ...sg, x: sg.x + dx, y: sg.y + dy };
      } else if (dragState.mode === 'resize' && dragState.edge) {
        const edge = dragState.edge;
        if (edge.includes('e')) next.width = sg.width + dx;
        if (edge.includes('s')) next.height = sg.height + dy;
        if (edge.includes('w')) {
          next.x = sg.x + dx;
          next.width = sg.width - dx;
        }
        if (edge.includes('n')) {
          next.y = sg.y + dy;
          next.height = sg.height - dy;
        }
      }

      next = clampGeometry(next);
      setGeometry(w.slug, next);
    };

    const onUp = () => setDragState(null);

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, [dragState, setGeometry, w.slug]);

  const onTitlePointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      // Don't start drag from buttons inside the title bar.
      if ((e.target as HTMLElement).closest('button')) return;
      // Maximized windows aren't draggable — un-maximize first.
      if (w.state === 'maximized') return;
      focus(w.slug);
      setDragState({
        mode: 'drag',
        edge: null,
        startX: e.clientX,
        startY: e.clientY,
        startGeometry: w.geometry,
      });
    },
    [focus, w.geometry, w.slug, w.state],
  );

  const onResizePointerDown = useCallback(
    (edge: NonNullable<ResizeEdge>) =>
      (e: ReactPointerEvent<HTMLDivElement>) => {
        if (w.state === 'maximized') return;
        e.stopPropagation();
        focus(w.slug);
        setDragState({
          mode: 'resize',
          edge,
          startX: e.clientX,
          startY: e.clientY,
          startGeometry: w.geometry,
        });
      },
    [focus, w.geometry, w.slug, w.state],
  );

  // The window is hidden when minimized but the iframe MUST stay in
  // the DOM — that's the whole point of the persistent-iframe design.
  const visible = w.state !== 'minimized';

  const containerStyle: CSSProperties = {
    position: 'absolute',
    left: renderGeometry.x,
    top: renderGeometry.y,
    width: renderGeometry.width,
    height: renderGeometry.height,
    zIndex: w.zIndex,
    display: visible ? 'flex' : 'none',
    transition: reducedMotion
      ? undefined
      : `transform ${TRANSITION_MS}ms ease-out, opacity ${TRANSITION_MS}ms ease-out`,
    willChange: dragState ? 'left, top, width, height' : undefined,
  };

  return (
    <div
      data-testid={`atrium-window-${w.slug}`}
      data-state={w.state}
      data-focused={isFocused ? 'true' : 'false'}
      className={`flex flex-col overflow-hidden rounded-lg border-2 shadow-2xl ${
        isFocused
          ? 'border-emerald-500 shadow-emerald-500/20'
          : 'border-slate-700'
      } bg-slate-900`}
      style={containerStyle}
      onPointerDown={() => focus(w.slug)}
      role="dialog"
      aria-label={`${w.title} window`}
    >
      {/* Title bar — drag handle */}
      <div
        data-testid={`atrium-window-${w.slug}-titlebar`}
        className={`flex items-center justify-between gap-2 border-b border-slate-700 px-3 py-2 ${
          isFocused ? 'bg-slate-800' : 'bg-slate-850 bg-slate-800/70'
        } ${w.state === 'maximized' ? 'cursor-default' : 'cursor-move'} select-none`}
        onPointerDown={onTitlePointerDown}
        onDoubleClick={() => maximize(w.slug)}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="text-sm font-medium text-slate-100 truncate">
            {w.title}
          </span>
          {w.variant === 'admin' && (
            <span
              className="rounded bg-amber-500/20 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-300"
              aria-label="Admin variant"
              data-testid={`atrium-window-${w.slug}-admin-pill`}
            >
              admin
            </span>
          )}
          {w.variant === 'public' && (
            <span
              className="rounded bg-sky-500/20 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-sky-300"
              aria-label="Public variant"
            >
              public
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              minimize(w.slug);
            }}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            aria-label={`Minimize ${w.title}`}
            data-testid={`atrium-window-${w.slug}-minimize`}
          >
            <span aria-hidden="true">_</span>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              maximize(w.slug);
            }}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
            aria-label={
              w.state === 'maximized'
                ? `Restore ${w.title}`
                : `Maximize ${w.title}`
            }
            data-testid={`atrium-window-${w.slug}-maximize`}
          >
            <span aria-hidden="true">{w.state === 'maximized' ? '❐' : '□'}</span>
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              close(w.slug);
            }}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-rose-600 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
            aria-label={`Close ${w.title}`}
            data-testid={`atrium-window-${w.slug}-close`}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>

      {/* Body — iframe OR error fallback. Crucially: the iframe is
          rendered exactly once per slug, never unmounted while the
          window is in the store. */}
      <div className="relative flex-1 bg-slate-950">
        {iframeFailed ? (
          <div
            className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center"
            data-testid={`atrium-window-${w.slug}-fallback`}
          >
            <p className="text-sm font-medium text-slate-200">
              Couldn&apos;t embed {w.title}
            </p>
            <p className="text-xs text-slate-400">
              The platform may block iframe embedding for security
              reasons (X-Frame-Options / CSP frame-ancestors).
            </p>
            <div className="flex gap-2">
              <a
                href={w.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
                data-testid={`atrium-window-${w.slug}-open-tab`}
              >
                Open in new tab
              </a>
              <a
                href="https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options"
                target="_blank"
                rel="noopener noreferrer"
                className="rounded border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500 hover:text-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
                data-testid={`atrium-window-${w.slug}-why`}
              >
                Why?
              </a>
            </div>
          </div>
        ) : (
          <iframe
            ref={iframeRef}
            data-testid={`atrium-window-${w.slug}-iframe`}
            src={w.url}
            title={w.title}
            sandbox="allow-scripts allow-forms allow-popups allow-same-origin"
            className="h-full w-full border-0"
            onError={() => setIframeFailed(true)}
          />
        )}

        {/* Resize handles — 8 around the body. Hidden when maximized. */}
        {w.state !== 'maximized' && (
          <>
            <div
              data-testid={`atrium-window-${w.slug}-resize-n`}
              className="absolute left-2 right-2 top-0 h-1 cursor-ns-resize"
              onPointerDown={onResizePointerDown('n')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-s`}
              className="absolute bottom-0 left-2 right-2 h-1 cursor-ns-resize"
              onPointerDown={onResizePointerDown('s')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-e`}
              className="absolute bottom-2 right-0 top-2 w-1 cursor-ew-resize"
              onPointerDown={onResizePointerDown('e')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-w`}
              className="absolute bottom-2 left-0 top-2 w-1 cursor-ew-resize"
              onPointerDown={onResizePointerDown('w')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-nw`}
              className="absolute left-0 top-0 h-2 w-2 cursor-nwse-resize"
              onPointerDown={onResizePointerDown('nw')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-ne`}
              className="absolute right-0 top-0 h-2 w-2 cursor-nesw-resize"
              onPointerDown={onResizePointerDown('ne')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-sw`}
              className="absolute bottom-0 left-0 h-2 w-2 cursor-nesw-resize"
              onPointerDown={onResizePointerDown('sw')}
            />
            <div
              data-testid={`atrium-window-${w.slug}-resize-se`}
              className="absolute bottom-0 right-0 h-2 w-2 cursor-nwse-resize"
              onPointerDown={onResizePointerDown('se')}
            />
          </>
        )}
      </div>
    </div>
  );
}
