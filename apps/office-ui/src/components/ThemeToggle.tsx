'use client';

import { useTheme, type ThemeMode } from './ThemeProvider';

const NEXT_MODE: Record<ThemeMode, ThemeMode> = {
  auto: 'day',
  day: 'night',
  night: 'auto',
};

const MODE_ICON: Record<ThemeMode, string> = {
  auto: '🌗',
  day: '☀️',
  night: '🌙',
};

const MODE_LABEL: Record<ThemeMode, string> = {
  auto: 'Auto (follows the sun)',
  day: 'Day',
  night: 'Night',
};

/** Cycles auto → day → night. Compact enough for any chrome corner. */
export function ThemeToggle({ className = '' }: { className?: string }) {
  const { mode, resolved, setMode } = useTheme();
  return (
    <button
      type="button"
      onClick={() => setMode(NEXT_MODE[mode])}
      title={`Theme: ${MODE_LABEL[mode]} — click to change`}
      aria-label={`Theme: ${MODE_LABEL[mode]}, currently ${resolved}. Click to change.`}
      className={`inline-flex items-center gap-1.5 rounded-full border border-edge bg-surface-raised px-2.5 py-1 text-xs text-ink-muted transition-colors hover:text-ink ${className}`}
    >
      <span aria-hidden>{MODE_ICON[mode]}</span>
      <span className="capitalize">{mode === 'auto' ? `auto · ${resolved}` : mode}</span>
    </button>
  );
}
