'use client';

import { useEffect, useRef, useState } from 'react';
import { useJumanjiState } from './useJumanjiState';
import { JumanjiDeviceArt } from './JumanjiDeviceArt';
import { JumanjiPortalModal } from './JumanjiPortalModal';
import { emitJumanjiEvent, JUMANJI_EVENTS } from './jumanjiAnalytics';
import './jumanji.css';

interface JumanjiDeviceImplProps {
  userId?: string | null;
  orgId?: string | null;
  currentPage: string;
  placement?: 'inline' | 'corner';
}

/**
 * Inner implementation. Lazy-loaded by JumanjiDevice.tsx.
 *
 * Activation sequence:
 *   - Type J-U-M-A-N-J-I when the device has keyboard focus
 *     (preferred — accessible, intentional, game-flavoured).
 *   - Or 3 taps within 2.5s once the device is curious (pointer-only
 *     fallback for touch devices and motor-impaired users).
 *   - Hover for 1.5s OR keyboard focus also raises the device into
 *     `curious` state without unlocking — gives a discovery hint.
 *
 * State sequencing:
 *   resting -> curious   (focus or hover-1.5s or first tap)
 *   curious -> awakened  (>=3 letters of sequence matched OR 2nd tap)
 *   awakened -> portal   (full sequence OR 3rd tap)
 *   portal -> (open modal) -> resting/curious (after close)
 *
 * Persistence:
 *   localStorage key `jumanji_discovered=true` once they've ever
 *   reached portal state. Subsequent visits start in `curious` so
 *   returning users notice the device is awake. ?reset_jumanji=1
 *   query param wipes that flag for testing or re-discovery.
 */
export function JumanjiDeviceImpl({
  userId,
  orgId,
  currentPage,
  placement = 'inline',
}: JumanjiDeviceImplProps) {
  const {
    state,
    progress,
    discovered,
    reducedMotion,
    onPointerEnter,
    onPointerLeave,
    onFocus,
    onBlur,
    onActivate,
    onKeyDown,
    reset,
  } = useJumanjiState();

  const mountedAtRef = useRef<number>(Date.now());
  const seenEmittedRef = useRef<boolean>(false);
  const activatedEmittedRef = useRef<boolean>(false);
  const [tickFrame, setTickFrame] = useState(0);
  const [portalOpen, setPortalOpen] = useState(false);

  // Animation tick — drives dice/hex cycling. Cheap setInterval at
  // 5fps; pauses entirely when reduced-motion or resting.
  useEffect(() => {
    if (reducedMotion) return;
    if (state === 'resting') return;
    const id = setInterval(() => setTickFrame((f) => (f + 1) % 64), 200);
    return () => clearInterval(id);
  }, [state, reducedMotion]);

  // Emit "seen" once per mount, at any state >= resting.
  useEffect(() => {
    if (seenEmittedRef.current) return;
    seenEmittedRef.current = true;
    emitJumanjiEvent(JUMANJI_EVENTS.SEEN, {
      user_id: userId,
      org_id: orgId,
      current_page: currentPage,
      discovered_at: 0,
    });
  }, [userId, orgId, currentPage]);

  // Emit "activated" the first time we hit portal state.
  useEffect(() => {
    if (state !== 'portal' || activatedEmittedRef.current) return;
    activatedEmittedRef.current = true;
    emitJumanjiEvent(JUMANJI_EVENTS.ACTIVATED, {
      user_id: userId,
      org_id: orgId,
      current_page: currentPage,
      discovered_at: Date.now() - mountedAtRef.current,
    });
  }, [state, userId, orgId, currentPage]);

  const onStepIn = () => {
    setPortalOpen(true);
  };

  const onPortalClose = () => {
    setPortalOpen(false);
    reset();
  };

  const containerCls =
    placement === 'corner'
      ? 'fixed bottom-3 right-3 z-hud'
      : 'inline-flex items-center';

  return (
    <>
      <div className={containerCls}>
        <button
          type="button"
          aria-label={
            state === 'portal'
              ? 'Mysterious device — the dice has opened a portal. Press Enter to step in.'
              : 'Mysterious device — interact to explore.'
          }
          aria-describedby="jumanji-device-hint"
          aria-pressed={state === 'portal'}
          tabIndex={0}
          onPointerEnter={onPointerEnter}
          onPointerLeave={onPointerLeave}
          onFocus={onFocus}
          onBlur={onBlur}
          onClick={() => {
            if (state === 'portal') {
              onStepIn();
            } else {
              onActivate();
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              if (state === 'portal') onStepIn();
              else onActivate();
              return;
            }
            onKeyDown(e);
          }}
          data-jumanji-state={state}
          data-jumanji-progress={progress}
          data-jumanji-discovered={discovered ? 'true' : 'false'}
          className={[
            'jumanji-device-button',
            'group relative inline-flex h-[60px] w-[60px] items-center justify-center',
            'rounded-md focus-visible:outline focus-visible:outline-2',
            'focus-visible:outline-emerald-300 focus-visible:outline-offset-2',
            state === 'resting' ? 'opacity-70 hover:opacity-100' : 'opacity-100',
          ].join(' ')}
        >
          <JumanjiDeviceArt
            state={state}
            reducedMotion={reducedMotion}
            tickFrame={tickFrame}
          />

          {state === 'portal' && (
            <span
              role="status"
              className="jumanji-step-in-cta absolute -bottom-7 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-sm border border-emerald-500/70 bg-emerald-900/80 px-2 py-0.5 text-[9px] uppercase tracking-widest text-emerald-200 shadow-[0_0_12px_rgba(95,196,138,0.6)]"
            >
              Step in →
            </span>
          )}
        </button>

        <span
          id="jumanji-device-hint"
          className="sr-only"
        >
          {state === 'resting'
            ? 'A small wooden device with faint glyph carvings.'
            : state === 'curious'
              ? 'The glyphs glow. A dice begins to rumble. Type J U M A N J I to wake it.'
              : state === 'awakened'
                ? 'The dice is rolling. Hex cells cycle in the viewport. Keep typing.'
                : 'The dice has locked. A jungle-green portal hums. Press Enter to step in.'}
        </span>
      </div>

      <JumanjiPortalModal
        open={portalOpen}
        onClose={onPortalClose}
        userId={userId}
        orgId={orgId}
        discoveredAt={Date.now() - mountedAtRef.current}
        currentPage={currentPage}
      />
    </>
  );
}
