'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ThemeToggle } from './ThemeToggle';

/**
 * Gather-style pre-join A/V check (design brief surface #2).
 *
 * Centered dark camera-preview card with mic/cam toggles, a display-name
 * field, and a pill Join button. Devices are OFF by default and only
 * requested when the user turns one on — never auto-grab getUserMedia on
 * mount. All failure modes (no device, permission denied, insecure
 * context) degrade to the "Your camera is off" placeholder.
 */

const SKIP_KEY = 'selva:skip-prejoin';

export function shouldSkipPreJoin(): boolean {
  try {
    if (
      typeof localStorage === 'undefined' ||
      typeof localStorage.getItem !== 'function'
    ) {
      return false;
    }
    return localStorage.getItem(SKIP_KEY) === '1';
  } catch {
    return false;
  }
}

interface PreJoinScreenProps {
  spaceName: string;
  defaultName?: string;
  /** Lock the name field (demo visitors already picked a name). */
  nameLocked?: boolean;
  accountEmail?: string | null;
  onJoin: (opts: { name: string; micOn: boolean; camOn: boolean }) => void;
}

export function PreJoinScreen({
  spaceName,
  defaultName = '',
  nameLocked = false,
  accountEmail,
  onJoin,
}: PreJoinScreenProps) {
  const [name, setName] = useState(defaultName);
  const [micOn, setMicOn] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  // Acquire/release devices as toggles change; always release on unmount.
  useEffect(() => {
    let cancelled = false;
    async function sync() {
      stopStream();
      if (!micOn && !camOn) return;
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        setMediaError('Media devices unavailable in this browser');
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: micOn,
          video: camOn,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        setMediaError(null);
        if (camOn && videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch {
        if (!cancelled) {
          setMediaError('Permission denied or no device found');
          setMicOn(false);
          setCamOn(false);
        }
      }
    }
    void sync();
    return () => {
      cancelled = true;
    };
  }, [micOn, camOn, stopStream]);

  useEffect(() => () => stopStream(), [stopStream]);

  const join = useCallback(() => {
    if (dontShowAgain) {
      try {
        if (
          typeof localStorage !== 'undefined' &&
          typeof localStorage.setItem === 'function'
        ) {
          localStorage.setItem(SKIP_KEY, '1');
        }
      } catch {
        /* best-effort */
      }
    }
    stopStream();
    onJoin({ name: name.trim() || 'Visitor', micOn, camOn });
  }, [dontShowAgain, name, micOn, camOn, onJoin, stopStream]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface px-4">
      {accountEmail ? (
        <span className="fixed right-4 top-4 text-xs text-ink-muted">{accountEmail}</span>
      ) : null}
      <div className="fixed left-4 top-4">
        <ThemeToggle />
      </div>

      <div className="flex w-full max-w-4xl flex-col items-center gap-10 md:flex-row md:justify-center">
        {/* Camera preview card */}
        <div className="relative aspect-[4/3] w-full max-w-md overflow-hidden rounded-2xl bg-[rgb(24_24_24)] shadow-lg">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className={`h-full w-full object-cover ${camOn ? '' : 'hidden'}`}
          />
          {!camOn && (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="text-sm text-[rgb(160_160_160)]">
                {mediaError ?? 'Your camera is off'}
              </p>
            </div>
          )}
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-2">
            <button
              type="button"
              onClick={() => setMicOn((v) => !v)}
              aria-pressed={micOn}
              aria-label={micOn ? 'Turn microphone off' : 'Turn microphone on'}
              className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                micOn
                  ? 'bg-accent text-accent-fg'
                  : 'bg-[rgb(45_45_45)] text-[rgb(230_80_80)]'
              }`}
            >
              {micOn ? '🎙️' : '🔇'}
            </button>
            <button
              type="button"
              onClick={() => setCamOn((v) => !v)}
              aria-pressed={camOn}
              aria-label={camOn ? 'Turn camera off' : 'Turn camera on'}
              className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                camOn
                  ? 'bg-accent text-accent-fg'
                  : 'bg-[rgb(45_45_45)] text-[rgb(230_80_80)]'
              }`}
            >
              {camOn ? '📹' : '🚫'}
            </button>
          </div>
        </div>

        {/* Join column */}
        <div className="w-full max-w-xs">
          <h1 className="mb-6 text-center text-xl font-semibold text-ink md:text-left">
            Welcome to {spaceName}
          </h1>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            maxLength={30}
            disabled={nameLocked}
            aria-label="Display name"
            onKeyDown={(e) => {
              if (e.key === 'Enter') join();
            }}
            className="mb-3 w-full rounded-lg border border-edge bg-surface-raised px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            onClick={join}
            className="w-full rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90"
          >
            Join
          </button>
          <label className="mt-4 flex cursor-pointer items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(e) => setDontShowAgain(e.target.checked)}
              className="accent-[rgb(var(--accent))]"
            />
            Don&apos;t show this screen again
          </label>
        </div>
      </div>
    </main>
  );
}
