'use client';

import { type FC, useState, useRef, useEffect } from 'react';
import type { PlayerStatusType } from '@/hooks/usePlayerStatus';

interface StatusSelectorProps {
  currentStatus: PlayerStatusType;
  onStatusChange: (status: PlayerStatusType) => void;
}

const STATUS_OPTIONS: Array<{ value: PlayerStatusType; label: string; color: string; dot: string }> = [
  { value: 'online', label: 'Online', color: 'text-emerald-400', dot: 'bg-emerald-400' },
  { value: 'away', label: 'Away', color: 'text-amber-400', dot: 'bg-amber-400' },
  { value: 'busy', label: 'Busy', color: 'text-red-400', dot: 'bg-red-400' },
  { value: 'dnd', label: 'DND', color: 'text-slate-500', dot: 'bg-slate-500' },
];

export const StatusSelector: FC<StatusSelectorProps> = ({ currentStatus, onStatusChange }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const current = STATUS_OPTIONS.find((o) => o.value === currentStatus) ?? STATUS_OPTIONS[0];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="retro-panel touch-target flex items-center gap-2 px-3 py-1.5 font-mono text-[8px] cursor-pointer hover:bg-slate-700/50 transition-colors"
        aria-label={`Status: ${current.label}. Click to change.`}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={`inline-block h-2 w-2 rounded-full ${current.dot}`} aria-hidden="true" />
        <span className={current.color}>{current.label}</span>
      </button>

      {open && (
        <ul
          className="absolute left-0 top-full mt-1 z-modal retro-panel py-1 min-w-[100px] animate-fade-in"
          role="listbox"
          aria-label="Player status"
        >
          {STATUS_OPTIONS.map((opt) => (
            <li key={opt.value} role="none">
              <button
                onClick={() => {
                  onStatusChange(opt.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-[8px] font-mono hover:bg-slate-700/50 transition-colors ${
                  opt.value === currentStatus ? 'bg-slate-700/30' : ''
                }`}
                role="option"
                aria-selected={opt.value === currentStatus}
              >
                <span className={`inline-block h-2 w-2 rounded-full ${opt.dot}`} aria-hidden="true" />
                <span className={opt.color}>{opt.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
