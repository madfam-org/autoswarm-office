'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { WFCGrid, buildOfficeRules } from '@selva/map-gen';

/**
 * Office-size onboarding (Gather v2 design brief surface #4). A size picker
 * with a live procedurally-generated office preview that re-renders per size,
 * plus the Selva twist: size → suggested pricing tier → upsell CTA (the
 * office-size moment doubles as an upgrade nudge).
 *
 * The preview uses the (previously orphaned) `@selva/map-gen` WFC generator —
 * this is its first real consumer. Generation is cheap at preview grid sizes
 * and seeded per bucket so it's stable, not flickering.
 */

interface SizeBucket {
  id: string;
  label: string;
  /** Departments to seed the preview WFC with (drives visual density). */
  departments: number;
  /** Suggested subscription tier for this size. */
  tier: 'starter' | 'professional' | 'enterprise';
  tierLabel: string;
}

const BUCKETS: SizeBucket[] = [
  { id: '1-10', label: '1–10', departments: 3, tier: 'starter', tierLabel: 'Starter' },
  { id: '11-20', label: '11–20', departments: 4, tier: 'professional', tierLabel: 'Professional' },
  { id: '21-50', label: '21–50', departments: 6, tier: 'professional', tierLabel: 'Professional' },
  { id: '51-80', label: '51–80', departments: 8, tier: 'enterprise', tierLabel: 'Enterprise' },
  { id: '81-100', label: '81–100', departments: 10, tier: 'enterprise', tierLabel: 'Enterprise' },
];

const PREVIEW_W = 32;
const PREVIEW_H = 22;
const CELL = 8;

// Meta-tile → preview color. Departments cycle through a tropical palette so
// bigger offices visibly gain more rooms.
const DEPT_COLORS = ['#4ade80', '#22d3ee', '#f6d55c', '#fb923c', '#a78bfa', '#f472b6', '#34d399', '#60a5fa', '#facc15', '#fb7185'];

function tileColor(tile: string): string {
  if (tile === 'wall') return '#1d3529';
  if (tile === 'corridor') return '#e8dcc4';
  if (tile.startsWith('dept_wall_')) return '#2a4a39';
  if (tile.startsWith('dept_')) {
    const n = Number(tile.slice('dept_'.length)) || 0;
    return DEPT_COLORS[n % DEPT_COLORS.length];
  }
  return '#e8dcc4';
}

function generatePreview(departments: number, seed: number): string[][] | null {
  try {
    const { rules, allTiles } = buildOfficeRules(departments);
    const grid = new WFCGrid({
      width: PREVIEW_W,
      height: PREVIEW_H,
      rules,
      allTiles,
      seed,
      maxRetries: 6,
    });
    return grid.run();
  } catch {
    return null;
  }
}

interface OfficeSizePickerProps {
  /** Called with the chosen bucket id + suggested tier when the user continues. */
  onContinue: (choice: { sizeId: string; tier: string }) => void;
  /** Optional upsell — start checkout for the suggested tier. */
  onUpgrade?: (tier: string) => void;
}

export function OfficeSizePicker({ onContinue, onUpgrade }: OfficeSizePickerProps) {
  const [selected, setSelected] = useState<SizeBucket>(BUCKETS[0]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Fixed seed per bucket → stable preview (regenerates only on size change).
  const grid = useMemo(
    () => generatePreview(selected.departments, selected.departments * 1000 + 7),
    [selected],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#e8dcc4';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!grid) return;
    for (let y = 0; y < grid.length; y++) {
      for (let x = 0; x < grid[y].length; x++) {
        ctx.fillStyle = tileColor(grid[y][x]);
        ctx.fillRect(x * CELL, y * CELL, CELL, CELL);
      }
    }
  }, [grid]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface px-4 py-10">
      <div className="flex w-full max-w-4xl flex-col gap-8 md:flex-row md:items-center">
        {/* Left: picker */}
        <div className="w-full md:max-w-xs">
          <h1 className="mb-1 text-xl font-semibold text-ink">Choose your office size</h1>
          <p className="mb-5 text-sm text-ink-muted">
            This sets your initial rooms and suggests a plan. You can change it later.
          </p>

          <div className="space-y-2" role="radiogroup" aria-label="Office size">
            {BUCKETS.map((b) => {
              const active = b.id === selected.id;
              return (
                <button
                  key={b.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setSelected(b)}
                  className={`flex w-full items-center justify-between rounded-lg border px-4 py-2.5 text-sm transition-colors ${
                    active
                      ? 'border-accent bg-surface-raised text-ink'
                      : 'border-edge bg-surface-raised text-ink-muted hover:text-ink'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    {active ? <span className="text-accent">✓</span> : null}
                    {b.label}
                  </span>
                  <span className="text-xs text-ink-muted">{b.tierLabel}</span>
                </button>
              );
            })}
          </div>

          {/* Tier hint + upsell */}
          <div className="mt-5 rounded-lg border border-edge bg-surface-raised p-3">
            <p className="text-xs text-ink-muted">
              Suggested plan for this size:{' '}
              <span className="font-medium text-ink">{selected.tierLabel}</span>
            </p>
            {onUpgrade && selected.tier !== 'starter' ? (
              <button
                type="button"
                onClick={() => onUpgrade(selected.tier)}
                className="mt-2 text-xs text-accent underline-offset-2 hover:underline"
              >
                Upgrade to {selected.tierLabel} →
              </button>
            ) : null}
          </div>

          <button
            type="button"
            onClick={() => onContinue({ sizeId: selected.id, tier: selected.tier })}
            className="mt-5 w-full rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90"
          >
            Continue
          </button>
        </div>

        {/* Right: live procedural preview */}
        <div className="flex flex-1 items-center justify-center">
          <div className="rounded-2xl border border-edge bg-[rgb(var(--accent-100))] p-4 shadow-lg">
            <canvas
              ref={canvasRef}
              width={PREVIEW_W * CELL}
              height={PREVIEW_H * CELL}
              className="rounded-lg"
              role="img"
              aria-label={`Preview of an office sized for ${selected.label} people`}
            />
            {grid === null ? (
              <p className="mt-2 text-center text-xs text-ink-muted">Preview unavailable</p>
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}
