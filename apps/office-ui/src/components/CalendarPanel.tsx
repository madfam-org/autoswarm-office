'use client';

import { useState, useEffect, useCallback, type FC } from 'react';
import type { CalendarEvent, CalendarStatus } from '@/hooks/useCalendar';
import { gameEventBus } from '@/game/PhaserGame';
import { EVENT_CHAT_FOCUS } from '@/lib/constants';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';
import { formatHM } from '@/lib/format-time';

interface CalendarPanelProps {
  open: boolean;
  onClose: () => void;
  events: CalendarEvent[];
  isBusy: boolean;
  connected: boolean;
  status: CalendarStatus;
  error: string | null;
  onConnect: (
    provider: 'google' | 'microsoft',
    accessToken: string,
    refreshToken?: string,
  ) => Promise<boolean>;
  onDisconnect: () => Promise<boolean>;
  onRefresh: () => Promise<void>;
}

export const CalendarPanel: FC<CalendarPanelProps> = ({
  open,
  onClose,
  events,
  isBusy,
  connected,
  status,
  error,
  onConnect,
  onDisconnect,
  onRefresh,
}) => {
  const [visible, setVisible] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [refreshTokenInput, setRefreshTokenInput] = useState('');
  const [selectedProvider, setSelectedProvider] = useState<'google' | 'microsoft'>('google');
  const trapRef = useFocusTrap<HTMLElement>(open);
  const { addToast } = useToast();

  // Slide animation
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
    }
  }, [open]);

  useEffect(() => {
    if (error) {
      addToast(error, 'error');
    }
  }, [error, addToast]);

  // Suppress game input while text fields focused
  const handleFocus = useCallback(() => {
    gameEventBus.emit(EVENT_CHAT_FOCUS, true);
  }, []);
  const handleBlur = useCallback(() => {
    gameEventBus.emit(EVENT_CHAT_FOCUS, false);
  }, []);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleBlur();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose, handleBlur]);

  const handleConnect = useCallback(async () => {
    if (!tokenInput.trim()) return;
    const ok = await onConnect(
      selectedProvider,
      tokenInput.trim(),
      refreshTokenInput.trim() || undefined,
    );
    if (ok) {
      addToast(`Connected to ${selectedProvider} calendar`, 'success');
      setTokenInput('');
      setRefreshTokenInput('');
    }
  }, [tokenInput, refreshTokenInput, selectedProvider, onConnect, addToast]);

  const handleDisconnect = useCallback(async () => {
    const ok = await onDisconnect();
    if (ok) {
      addToast('Calendar disconnected', 'info');
    }
  }, [onDisconnect, addToast]);

  if (!open) return null;

  return (
    <aside
      ref={trapRef}
      className={`fixed right-0 top-0 z-modal h-full w-full max-w-80 transform transition-transform duration-300 sm:w-80 ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-label="Calendar panel"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex h-full flex-col bg-slate-900/95 backdrop-blur-sm pixel-border-accent">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <div className="flex items-center gap-2">
            <h2 className="pixel-text text-[10px] uppercase tracking-wider text-indigo-400">
              Calendar
            </h2>
            {connected && (
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
            )}
            {isBusy && (
              <span className="font-mono text-[7px] uppercase text-amber-400">
                In Meeting
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-200"
            aria-label="Close calendar panel"
          >
            ESC
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {connected ? (
            <>
              {/* Status Bar */}
              <div className="flex items-center justify-between">
                <span className="font-mono text-[8px] uppercase text-emerald-400">
                  Connected
                </span>
                <button
                  onClick={() => void onRefresh()}
                  className="rounded px-2 py-1 font-mono text-[8px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                >
                  Refresh
                </button>
              </div>

              {/* Events List */}
              {events.length === 0 ? (
                <p className="text-center font-mono text-[9px] text-slate-500 py-8">
                  No upcoming events
                </p>
              ) : (
                <div className="space-y-2">
                  {events.map((event) => (
                    <div
                      key={event.id}
                      className={`rounded border px-3 py-2 ${
                        isBusy && !event.is_all_day
                          ? 'border-amber-600/50 bg-amber-900/20'
                          : 'border-slate-700 bg-slate-800/60'
                      }`}
                    >
                      <p className="font-mono text-[9px] text-slate-200 font-bold">
                        {event.title}
                      </p>
                      <p className="font-mono text-[8px] text-slate-400 mt-0.5">
                        {event.is_all_day
                          ? 'All day'
                          : `${formatHM(event.start)} - ${formatHM(event.end)}`}
                      </p>
                      {event.organizer && (
                        <p className="font-mono text-[7px] text-slate-500 mt-0.5">
                          {event.organizer}
                        </p>
                      )}
                      {event.meeting_url && (
                        <a
                          href={event.meeting_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-block rounded bg-indigo-600/80 px-2 py-0.5 font-mono text-[8px] text-white hover:bg-indigo-500"
                        >
                          Join Meeting
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Disconnect */}
              <div className="pt-2 border-t border-slate-700">
                <button
                  onClick={() => void handleDisconnect()}
                  className="w-full rounded bg-red-900/40 px-3 py-2 font-mono text-[9px] text-red-400 hover:bg-red-900/60"
                >
                  Disconnect Calendar
                </button>
              </div>
            </>
          ) : (
            <>
              {/* Connect Form */}
              <p className="font-mono text-[9px] text-slate-400">
                Connect your calendar to auto-set your status to busy during meetings.
              </p>

              {/* Provider Selection */}
              <div>
                <label className="block font-mono text-[8px] uppercase text-slate-500 mb-1">
                  Provider
                </label>
                <div className="flex gap-2">
                  {(['google', 'microsoft'] as const).map((provider) => (
                    <button
                      key={provider}
                      onClick={() => setSelectedProvider(provider)}
                      className={`flex-1 rounded px-2 py-1.5 font-mono text-[8px] uppercase transition-colors ${
                        selectedProvider === provider
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-800 text-slate-400 hover:text-white'
                      }`}
                    >
                      {provider}
                    </button>
                  ))}
                </div>
              </div>

              {/* Access Token */}
              <div>
                <label className="block font-mono text-[8px] uppercase text-slate-500 mb-1">
                  Access Token *
                </label>
                <input
                  type="password"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  onFocus={handleFocus}
                  onBlur={handleBlur}
                  className="w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 font-mono text-[10px] text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                  placeholder="OAuth2 access token..."
                />
              </div>

              {/* Refresh Token (optional) */}
              <div>
                <label className="block font-mono text-[8px] uppercase text-slate-500 mb-1">
                  Refresh Token (optional)
                </label>
                <input
                  type="password"
                  value={refreshTokenInput}
                  onChange={(e) => setRefreshTokenInput(e.target.value)}
                  onFocus={handleFocus}
                  onBlur={handleBlur}
                  className="w-full rounded bg-slate-800 border border-slate-700 px-3 py-2 font-mono text-[10px] text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                  placeholder="Refresh token..."
                />
              </div>
            </>
          )}
        </div>

        {/* Footer (connect button, shown only when not connected) */}
        {!connected && (
          <div className="border-t border-slate-700 px-4 py-3">
            <button
              onClick={() => void handleConnect()}
              disabled={!tokenInput.trim() || status === 'connecting'}
              className="w-full rounded bg-indigo-600 px-4 py-2 font-mono text-[10px] uppercase text-white transition-colors hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed"
            >
              {status === 'connecting' ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Connecting...
                </span>
              ) : (
                'Connect Calendar'
              )}
            </button>
          </div>
        )}
      </div>
    </aside>
  );
};
