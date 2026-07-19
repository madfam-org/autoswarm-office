'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Department, Player } from '@selva/shared-types';

/**
 * ⌘K command palette (Gather v2 design brief surface #5). Global search over
 * the people AND agent-citizens in the space, plus quick actions. Opens on
 * ⌘K / Ctrl+K, closes on Esc; arrow keys + Enter navigate.
 *
 * Native (no cmdk dep) so it stays self-contained. Results are derived from
 * the same Colyseus state the roster uses — searching what you can already
 * see, plus the actions you'd otherwise hunt for in panels.
 */

export interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  glyph: string;
  run: () => void;
}

interface Entry {
  id: string;
  label: string;
  sub: string;
  glyph: string;
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  players: Player[];
  departments: Department[];
  /** Quick actions (Dispatch, Approvals, …) supplied by the office shell. */
  actions: PaletteAction[];
  /** Jump to a person on the map (locate/follow). */
  onSelectPlayer?: (sessionId: string) => void;
}

const AGENT_STATUS_LABEL: Record<string, string> = {
  working: 'Working',
  idle: 'Idle',
  waiting_approval: 'Awaiting approval',
  paused: 'Paused',
  error: 'Error',
};

export function CommandPalette({
  open,
  onClose,
  players,
  departments,
  actions,
  onSelectPlayer,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      // Focus after paint.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const entries = useMemo<Entry[]>(() => {
    const actionEntries: Entry[] = actions.map((a) => ({
      id: `action:${a.id}`,
      label: a.label,
      sub: a.hint ?? 'Action',
      glyph: a.glyph,
      run: a.run,
    }));

    const peopleEntries: Entry[] = players.map((p) => ({
      id: `player:${p.sessionId}`,
      label: p.name,
      sub: `Person · ${p.playerStatus ?? 'online'}`,
      glyph: '🧑',
      run: () => onSelectPlayer?.(p.sessionId),
    }));

    const agentEntries: Entry[] = departments
      .flatMap((d) => d.agents ?? [])
      .map((a) => ({
        id: `agent:${a.id}`,
        label: a.name,
        sub: `${a.role} · ${AGENT_STATUS_LABEL[a.status] ?? a.status}`,
        glyph: '🤖',
        run: () => undefined,
      }));

    const all = [...actionEntries, ...peopleEntries, ...agentEntries];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (e) => e.label.toLowerCase().includes(q) || e.sub.toLowerCase().includes(q),
    );
  }, [actions, players, departments, query, onSelectPlayer]);

  // Keep the active index in range as the filtered list shrinks.
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, entries.length - 1)));
  }, [entries.length]);

  const choose = useCallback(
    (entry: Entry | undefined) => {
      if (!entry) return;
      entry.run();
      onClose();
    },
    [onClose],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, entries.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        choose(entries[active]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    },
    [entries, active, choose, onClose],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-modal flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-edge bg-surface-raised shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search people, agents, actions…"
          aria-label="Search people, agents, and actions"
          className="w-full border-b border-edge bg-transparent px-4 py-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none"
        />
        <ul className="max-h-80 overflow-y-auto py-1" role="listbox">
          {entries.length === 0 ? (
            <li className="px-4 py-6 text-center text-sm text-ink-muted">No matches</li>
          ) : (
            entries.map((entry, i) => (
              <li key={entry.id} role="option" aria-selected={i === active}>
                <button
                  type="button"
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(entry)}
                  className={`flex w-full items-center gap-3 px-4 py-2 text-left ${
                    i === active ? 'bg-surface-overlay' : ''
                  }`}
                >
                  <span className="text-base" aria-hidden>
                    {entry.glyph}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm text-ink">
                    {entry.label}
                  </span>
                  <span className="flex-shrink-0 text-xs text-ink-muted">{entry.sub}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
