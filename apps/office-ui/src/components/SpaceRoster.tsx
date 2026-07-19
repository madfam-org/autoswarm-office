'use client';

import { useMemo } from 'react';
import type { Department, Player } from '@selva/shared-types';

/**
 * Persistent left-rail roster — the "instant visibility into your office"
 * surface (Gather v2 design brief #1). Shows who's in the space at a glance:
 * humans AND the AI agent-citizens, each with a presence dot and a status
 * chip. This is Selva's differentiator over Gather — agents appear on the
 * roster like teammates, not as a hidden backend fleet.
 *
 * Read-only + derived from Colyseus state already in OfficeExperience, so it
 * adds no new data path. Collapses on small screens (the map is primary).
 */

interface SpaceRosterProps {
  spaceName: string;
  players: Player[];
  departments: Department[];
  localSessionId: string;
  /** Click a human row to locate/follow them on the map (optional). */
  onSelectPlayer?: (sessionId: string) => void;
  /** Wave at a person or agent — walks the local avatar over to them and
   * plays the wave emote on arrival (optional; omit to hide the affordance). */
  onWave?: (target: { kind: 'player' | 'agent'; id: string }) => void;
}

type PresenceTone = 'online' | 'busy' | 'idle' | 'attention' | 'error';

const TONE_DOT: Record<PresenceTone, string> = {
  online: 'bg-[rgb(var(--accent-400))]',
  busy: 'bg-amber-400',
  idle: 'bg-[rgb(var(--tone-400))]',
  attention: 'bg-amber-400',
  error: 'bg-red-400',
};

// AI agent status → presence tone + human label.
const AGENT_STATUS: Record<string, { tone: PresenceTone; label: string }> = {
  working: { tone: 'online', label: 'Working' },
  idle: { tone: 'idle', label: 'Idle' },
  waiting_approval: { tone: 'attention', label: 'Awaiting approval' },
  paused: { tone: 'idle', label: 'Paused' },
  error: { tone: 'error', label: 'Error' },
};

const PLAYER_STATUS: Record<string, { tone: PresenceTone; label: string }> = {
  online: { tone: 'online', label: 'Active' },
  away: { tone: 'idle', label: 'Away' },
  busy: { tone: 'busy', label: 'Busy' },
  dnd: { tone: 'busy', label: 'Do not disturb' },
};

function Dot({ tone }: { tone: PresenceTone }) {
  return (
    <span
      className={`inline-block h-2 w-2 flex-shrink-0 rounded-full ${TONE_DOT[tone]}`}
      aria-hidden
    />
  );
}

function WaveButton({ name, onWave }: { name: string; onWave: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onWave();
      }}
      className="flex-shrink-0 rounded p-1 text-sm leading-none opacity-70 transition-opacity hover:bg-surface-overlay hover:opacity-100"
      title={`Wave at ${name}`}
      aria-label={`Wave at ${name}`}
    >
      <span aria-hidden>{'\u{1F44B}'}</span>
    </button>
  );
}

function RosterRow({
  name,
  statusLabel,
  tone,
  badge,
  onClick,
  onWave,
}: {
  name: string;
  statusLabel: string;
  tone: PresenceTone;
  badge?: string;
  onClick?: () => void;
  onWave?: () => void;
}) {
  const Wrapper = onClick ? 'button' : 'div';
  const row = (
    <Wrapper
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left ${
        onClick ? 'transition-colors hover:bg-surface-overlay' : ''
      }`}
    >
      <Dot tone={tone} />
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{name}</span>
      {badge ? (
        <span className="flex-shrink-0 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-muted">
          {badge}
        </span>
      ) : null}
      <span className="flex-shrink-0 text-[11px] text-ink-muted">{statusLabel}</span>
    </Wrapper>
  );

  // The wave button is a sibling, never nested inside the row's own
  // <button> wrapper (onSelectPlayer rows) — nesting interactive controls
  // is invalid HTML and breaks click targeting/focus order.
  if (!onWave) return row;
  return (
    <div className="flex w-full items-center gap-1">
      {row}
      <WaveButton name={name} onWave={onWave} />
    </div>
  );
}

export function SpaceRoster({
  spaceName,
  players,
  departments,
  localSessionId,
  onSelectPlayer,
  onWave,
}: SpaceRosterProps) {
  const { you, otherHumans, agents } = useMemo(() => {
    const you = players.find((p) => p.sessionId === localSessionId) ?? null;
    const otherHumans = players.filter((p) => p.sessionId !== localSessionId);
    // `d.agents` can be a Colyseus ArraySchema proxy rather than a real
    // Array (depending on how state reached this component) — it supports
    // .length/.forEach/[Symbol.iterator] but fails Array.isArray(), so
    // Array.prototype.flatMap silently treats it as a single non-flattening
    // element instead of spreading its items. Array.from() normalizes any
    // array-like/iterable into a true array first, which flatMap then
    // flattens correctly.
    const agents = departments.flatMap((d) => (d.agents ? Array.from(d.agents) : []));
    return { you, otherHumans, agents };
  }, [players, departments, localSessionId]);

  const humanCount = players.length;
  const agentCount = agents.length;

  return (
    <aside
      className="pointer-events-auto hidden h-full w-64 flex-col border-r border-edge bg-surface md:flex"
      aria-label="Space roster"
    >
      <div className="border-b border-edge px-4 py-3">
        <h2 className="truncate text-sm font-semibold text-ink">{spaceName}</h2>
        <p className="mt-0.5 text-xs text-ink-muted">
          {humanCount} {humanCount === 1 ? 'person' : 'people'} · {agentCount}{' '}
          {agentCount === 1 ? 'agent' : 'agents'}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {/* You */}
        {you ? (
          <div className="mb-2">
            <RosterRow
              name={`${you.name} (you)`}
              tone={PLAYER_STATUS[you.playerStatus ?? 'online']?.tone ?? 'online'}
              statusLabel={PLAYER_STATUS[you.playerStatus ?? 'online']?.label ?? 'Active'}
            />
          </div>
        ) : null}

        {/* Other humans */}
        {otherHumans.length > 0 ? (
          <div className="mb-2">
            <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-ink-muted">
              People
            </p>
            {otherHumans.map((p) => {
              const s = PLAYER_STATUS[p.playerStatus ?? 'online'] ?? {
                tone: 'online' as PresenceTone,
                label: 'Active',
              };
              return (
                <RosterRow
                  key={p.sessionId}
                  name={p.name}
                  tone={s.tone}
                  statusLabel={s.label}
                  onClick={onSelectPlayer ? () => onSelectPlayer(p.sessionId) : undefined}
                  onWave={onWave ? () => onWave({ kind: 'player', id: p.sessionId }) : undefined}
                />
              );
            })}
          </div>
        ) : null}

        {/* Agent-citizens — Selva's differentiator */}
        {agentCount > 0 ? (
          <div>
            <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-ink-muted">
              Agents
            </p>
            {agents.map((a) => {
              const s = AGENT_STATUS[a.status] ?? {
                tone: 'idle' as PresenceTone,
                label: a.status,
              };
              return (
                <RosterRow
                  key={a.id}
                  name={a.name}
                  tone={s.tone}
                  statusLabel={s.label}
                  badge={a.role}
                  onWave={onWave ? () => onWave({ kind: 'agent', id: a.id }) : undefined}
                />
              );
            })}
          </div>
        ) : null}

        {humanCount === 0 && agentCount === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-ink-muted">
            The office is quiet. Dispatch a task to bring an agent to life.
          </p>
        ) : null}
      </div>
    </aside>
  );
}
