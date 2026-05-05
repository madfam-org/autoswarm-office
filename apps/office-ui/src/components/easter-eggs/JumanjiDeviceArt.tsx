'use client';

import { memo } from 'react';
import type { JumanjiState } from './useJumanjiState';

interface JumanjiDeviceArtProps {
  state: JumanjiState;
  reducedMotion: boolean;
  /** 0..7 — drives subtle dice face cycling without a ref. */
  tickFrame: number;
}

const GLYPHS = ['◬', '◊', '⌬', '✦', '⟁', '☘', '☼', '◉'];

/**
 * The wooden-box-meets-arcade-cabinet artifact. Pure SVG + CSS, no
 * canvas, no three.js. Total markup is ~3.2KB before gzip; the
 * stylesheet is colocated so callers don't need to import another
 * file.
 *
 * Visual vocabulary:
 *   - resting:  warm wood (#5e4630), faint moss-green glyph carvings,
 *               a closed lid with two iron rivets.
 *   - curious:  glyphs glow #d8b878 (solar), a small dice peeks from
 *               a slit at the top.
 *   - awakened: dice fully visible, faces cycle through GLYPHS, a
 *               viewport at center cycles through hex-grid frames
 *               (Rondelio's visual vocabulary).
 *   - portal:   jungle-green (#2f7a4a) bloom from the viewport, dice
 *               locks on a central glyph, "Step in" CTA fades up.
 */
export const JumanjiDeviceArt = memo(function JumanjiDeviceArt({
  state,
  reducedMotion,
  tickFrame,
}: JumanjiDeviceArtProps) {
  const glow = state !== 'resting';
  const showDice = state === 'curious' || state === 'awakened' || state === 'portal';
  const showViewport = state === 'awakened' || state === 'portal';
  const portal = state === 'portal';

  // When reduced-motion is on, we lock the dice to a single neutral
  // face so nothing pulses or rotates.
  const diceGlyph = reducedMotion
    ? GLYPHS[0]
    : portal
    ? '✦'
    : GLYPHS[tickFrame % GLYPHS.length];

  // Hex grid frame cycle (8 phases). Just an opacity rotation across
  // a 7-cell honeycomb so the viewport feels alive.
  const hexCycle = reducedMotion ? 0 : tickFrame % 7;

  return (
    <svg
      viewBox="0 0 60 60"
      width="60"
      height="60"
      role="img"
      aria-hidden="true"
      className={[
        'jumanji-device-art',
        glow ? 'jumanji-device-art--glow' : '',
        portal ? 'jumanji-device-art--portal' : '',
        reducedMotion ? 'jumanji-device-art--reduced-motion' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <defs>
        <linearGradient id="wood" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6b4f33" />
          <stop offset="100%" stopColor="#3e2c1c" />
        </linearGradient>
        <radialGradient id="portal-bloom" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#5fc48a" stopOpacity="0.95" />
          <stop offset="65%" stopColor="#2f7a4a" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#0e2a18" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="iron" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7a6450" />
          <stop offset="100%" stopColor="#3a2e22" />
        </linearGradient>
      </defs>

      {/* Outer wooden box */}
      <rect
        x="4"
        y="6"
        width="52"
        height="50"
        rx="4"
        ry="4"
        fill="url(#wood)"
        stroke="#1f140a"
        strokeWidth="1.5"
      />

      {/* Wood grain — three horizontal etched lines */}
      <path
        d="M7 18 L53 18 M7 30 L53 30 M7 42 L53 42"
        stroke="#2a1d10"
        strokeWidth="0.4"
        strokeLinecap="round"
        opacity="0.55"
      />

      {/* Iron rivets — top corners */}
      <circle cx="9" cy="11" r="1.5" fill="url(#iron)" />
      <circle cx="51" cy="11" r="1.5" fill="url(#iron)" />
      <circle cx="9" cy="51" r="1.5" fill="url(#iron)" />
      <circle cx="51" cy="51" r="1.5" fill="url(#iron)" />

      {/* Glyph carvings (top + bottom borders) */}
      <g
        className={glow ? 'jumanji-glyph jumanji-glyph--glow' : 'jumanji-glyph'}
        fontSize="6"
        fontFamily="serif"
        textAnchor="middle"
        fill="#a48b5a"
      >
        <text x="18" y="16">◬</text>
        <text x="30" y="16">⌬</text>
        <text x="42" y="16">⟁</text>
        <text x="18" y="54">☘</text>
        <text x="30" y="54">✦</text>
        <text x="42" y="54">◊</text>
      </g>

      {/* Inner viewport — appears at awakened+ */}
      {showViewport && (
        <g>
          <rect
            x="20"
            y="22"
            width="20"
            height="16"
            rx="1.5"
            fill={portal ? 'url(#portal-bloom)' : '#1a2820'}
            stroke="#0b150e"
            strokeWidth="0.8"
          />
          {/* Hex grid — 7 cells */}
          {[
            { cx: 30, cy: 26 },
            { cx: 25, cy: 28.5 },
            { cx: 35, cy: 28.5 },
            { cx: 25, cy: 33.5 },
            { cx: 35, cy: 33.5 },
            { cx: 30, cy: 36 },
            { cx: 30, cy: 30 },
          ].map((cell, i) => (
            <polygon
              key={i}
              points={hexPoints(cell.cx, cell.cy, 1.8)}
              fill={portal ? '#a8e8c1' : '#5fc48a'}
              opacity={
                reducedMotion ? 0.55 : i === hexCycle ? 0.95 : 0.35 + ((i + tickFrame) % 3) * 0.08
              }
            />
          ))}
        </g>
      )}

      {/* Dice — appears at curious+ */}
      {showDice && (
        <g
          className={
            portal
              ? 'jumanji-dice jumanji-dice--locked'
              : 'jumanji-dice jumanji-dice--rolling'
          }
        >
          <rect
            x="26"
            y="9"
            width="8"
            height="8"
            rx="1"
            fill="#e8dcc0"
            stroke="#4a3a26"
            strokeWidth="0.6"
          />
          <text
            x="30"
            y="15.5"
            fontSize="6"
            fontFamily="serif"
            textAnchor="middle"
            fill="#3a2a18"
          >
            {diceGlyph}
          </text>
        </g>
      )}

      {/* Portal bloom rim */}
      {portal && (
        <rect
          x="4"
          y="6"
          width="52"
          height="50"
          rx="4"
          ry="4"
          fill="none"
          stroke="#5fc48a"
          strokeWidth="1.4"
          opacity="0.85"
          className="jumanji-portal-rim"
        />
      )}
    </svg>
  );
});

function hexPoints(cx: number, cy: number, r: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 6;
    pts.push(`${(cx + r * Math.cos(angle)).toFixed(2)},${(cy + r * Math.sin(angle)).toFixed(2)}`);
  }
  return pts.join(' ');
}
