'use client';

import { useState, useEffect, useCallback } from 'react';
import { gameEventBus } from '@/game/PhaserGame';

const EMOTES = [
  { type: 'wave', label: 'Wave', icon: '\u{1F44B}' },
  { type: 'thumbsup', label: 'Thumbs Up', icon: '\u{1F44D}' },
  { type: 'heart', label: 'Heart', icon: '\u{2764}\u{FE0F}' },
  { type: 'laugh', label: 'Laugh', icon: '\u{1F602}' },
  { type: 'think', label: 'Think', icon: '\u{1F914}' },
  { type: 'clap', label: 'Clap', icon: '\u{1F44F}' },
  { type: 'fire', label: 'Fire', icon: '\u{1F525}' },
  { type: 'sparkle', label: 'Sparkle', icon: '\u{2728}' },
  { type: 'coffee', label: 'Coffee', icon: '\u{2615}' },
] as const;

interface EmotePickerProps {
  onEmote: (type: string) => void;
}

export function EmotePicker({ onEmote }: EmotePickerProps) {
  const [open, setOpen] = useState(false);

  const handleEmote = useCallback(
    (type: string) => {
      onEmote(type);
      setOpen(false);
    },
    [onEmote],
  );

  // R key toggles the picker; 1-9 quick-select when open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        setOpen((prev) => !prev);
        return;
      }

      if (open) {
        const num = parseInt(e.key, 10);
        if (num >= 1 && num <= 9) {
          e.preventDefault();
          handleEmote(EMOTES[num - 1].type);
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          setOpen(false);
        }
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, handleEmote]);

  // Emit emote-picker-focus so GamepadManager can suppress movement
  useEffect(() => {
    gameEventBus.emit('emote-picker-focus', open);
  }, [open]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="absolute bottom-4 right-4 z-hud rounded bg-slate-800/90 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
        title="Emotes [R]"
      >
        Emotes [R]
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 z-hud rounded border border-slate-700 bg-slate-900/95 p-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400">EMOTES</span>
        <button
          onClick={() => setOpen(false)}
          className="text-xs text-slate-500 hover:text-slate-300"
          aria-label="Close emotes"
        >
          Esc
        </button>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {EMOTES.map((emote, i) => (
          <button
            key={emote.type}
            onClick={() => handleEmote(emote.type)}
            className="flex flex-col items-center gap-0.5 rounded p-2 text-center hover:bg-slate-800"
            title={`${emote.label} [${i + 1}]`}
            aria-label={`${emote.label} - Press ${i + 1}`}
          >
            <span className="text-xl">{emote.icon}</span>
            <span className="text-[8px] text-slate-500">{i + 1}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
