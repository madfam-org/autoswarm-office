'use client';

/**
 * Pure CSS+SVG illustrations of the egg at each lifecycle stage.
 *
 * No image assets, no canvas, no 3D library — just an SVG ellipse
 * with stage-specific texture, glow, cracks, and (for the matured
 * stage) a tiny dragon emerging.
 *
 * Animation is gated behind ``@media (prefers-reduced-motion: no-preference)``
 * — operators on reduced-motion see static art with no pulse / no
 * crack-shake.
 *
 * Platform tinting (only at the matured stage):
 *   - Mastodon: tusks (small triangular protrusions, purple-ish hue)
 *   - Bluesky:  butterfly wings (translucent blue)
 *   - Reddit:   orange-and-white scaled ridges
 *
 * Styling: pulled from the existing solarpunk palette so the dragon
 * UI feels of-a-piece with the rest of the office. No emoji. No
 * sales superlatives. The color story is "stone egg → warm glow →
 * crack → dragon emerging" — a natural progression.
 */

import type { EggPlatform, EggStatus } from './types';

interface EggArtProps {
  status: EggStatus;
  platform: EggPlatform;
  /** Display size in pixels (square). Default 96px (card-friendly). */
  size?: number;
  /** Optional className for layout adjustments (margin, etc.). */
  className?: string;
}

/**
 * Solarpunk palette references kept inline so this component can be
 * imported as a leaf widget without a Tailwind context (used in
 * snapshot tests).
 */
const STAGE_COLORS: Record<
  EggStatus,
  {
    shellOuter: string;
    shellInner: string;
    glow: string | null;
    crackOpacity: number;
  }
> = {
  laid: {
    shellOuter: '#6b5a42', // solarpunk wood-dark
    shellInner: '#a89878', // solarpunk wood-light
    glow: null,
    crackOpacity: 0,
  },
  incubating: {
    shellOuter: '#8b7355',
    shellInner: '#c8b896',
    glow: '#f6d55c33', // solar at 20%
    crackOpacity: 0,
  },
  hatching: {
    shellOuter: '#a89878',
    shellInner: '#e8dcc4',
    glow: '#f6d55c66', // solar at 40%
    crackOpacity: 0.85,
  },
  hatched: {
    shellOuter: '#a89878',
    shellInner: '#e8dcc4',
    glow: '#f6d55c80', // solar at 50%
    crackOpacity: 1,
  },
  matured: {
    shellOuter: '#a89878',
    shellInner: '#e8dcc4',
    glow: '#a8d8b9', // glow (matured)
    crackOpacity: 1,
  },
};

const PLATFORM_DRAGON_TINT: Record<EggPlatform, string> = {
  // Tone-down hues so the matured egg reads "of-a-piece" with the
  // rest of the office, not a billboard.
  mastodon: '#6b5a8c', // soft purple
  bluesky: '#7fbada', // soft blue
  reddit: '#d18a4f', // soft orange
};

export function EggArt({ status, platform, size = 96, className = '' }: EggArtProps) {
  const stage = STAGE_COLORS[status];
  const dragonTint = PLATFORM_DRAGON_TINT[platform];

  // Center & extents — using a 100x120 viewBox lets the egg taper
  // naturally (taller than wide).
  const VB_W = 100;
  const VB_H = 120;
  const cx = VB_W / 2;
  const cy = VB_H / 2 + 5;
  const rx = 36;
  const ry = 48;

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      width={size}
      height={size}
      role="img"
      aria-label={`${platform} egg, ${status}`}
      data-testid={`egg-art-${status}`}
      className={`egg-art egg-art-${status} ${className}`.trim()}
    >
      {/* Glow halo — only present from incubating onward.
          Animation disabled under prefers-reduced-motion via the
          inline <style> below. */}
      {stage.glow && (
        <defs>
          <radialGradient id={`glow-${status}-${platform}`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={stage.glow} stopOpacity="0.9" />
            <stop offset="80%" stopColor={stage.glow} stopOpacity="0" />
          </radialGradient>
        </defs>
      )}

      {stage.glow && (
        <ellipse
          className="egg-art-glow"
          cx={cx}
          cy={cy}
          rx={rx + 14}
          ry={ry + 14}
          fill={`url(#glow-${status}-${platform})`}
        />
      )}

      {/* Shell — gradient from outer → inner so the egg has form
          without being photoreal. Stone-textured at 'laid' (no
          gradient stop offset; flat fill); warmer / brighter as it
          progresses. */}
      <defs>
        <radialGradient id={`shell-${status}-${platform}`} cx="40%" cy="35%" r="65%">
          <stop offset="0%" stopColor={stage.shellInner} />
          <stop offset="100%" stopColor={stage.shellOuter} />
        </radialGradient>
      </defs>
      <ellipse
        cx={cx}
        cy={cy}
        rx={rx}
        ry={ry}
        fill={`url(#shell-${status}-${platform})`}
        stroke={stage.shellOuter}
        strokeWidth="1"
      />

      {/* Stone speckle for laid/incubating — tiny dots that imply
          texture without screaming "this is a Pokémon egg". */}
      {(status === 'laid' || status === 'incubating') && (
        <g opacity="0.4">
          <circle cx={cx - 14} cy={cy - 18} r="1.2" fill={stage.shellOuter} />
          <circle cx={cx + 8} cy={cy - 8} r="0.9" fill={stage.shellOuter} />
          <circle cx={cx - 6} cy={cy + 14} r="1.1" fill={stage.shellOuter} />
          <circle cx={cx + 16} cy={cy + 22} r="0.8" fill={stage.shellOuter} />
        </g>
      )}

      {/* Cracks — visible at hatching/hatched/matured. Two
          lightning-bolt-ish polylines crossing the egg. */}
      {stage.crackOpacity > 0 && (
        <g
          className="egg-art-cracks"
          opacity={stage.crackOpacity}
          stroke="#3a2e1f"
          strokeWidth="1.4"
          strokeLinecap="round"
          fill="none"
        >
          <polyline points={`${cx - 18},${cy - 28} ${cx - 10},${cy - 18} ${cx - 16},${cy - 6} ${cx - 6},${cy + 4}`} />
          <polyline points={`${cx + 14},${cy - 14} ${cx + 6},${cy - 4} ${cx + 12},${cy + 10} ${cx + 4},${cy + 22}`} />
        </g>
      )}

      {/* Hatched: a tiny dragon emerging from the broken shell.
          Single triangle head + two simple eyes. */}
      {status === 'hatched' && (
        <g className="egg-art-hatchling">
          <path
            d={`M ${cx - 8} ${cy - 4} L ${cx} ${cy - 16} L ${cx + 8} ${cy - 4} Z`}
            fill={dragonTint}
            stroke="#1a1208"
            strokeWidth="0.6"
          />
          <circle cx={cx - 3} cy={cy - 8} r="0.8" fill="#fffcde" />
          <circle cx={cx + 3} cy={cy - 8} r="0.8" fill="#fffcde" />
        </g>
      )}

      {/* Matured: full dragon, platform-themed. */}
      {status === 'matured' && (
        <g className="egg-art-dragon">
          {/* Body */}
          <ellipse cx={cx} cy={cy} rx={rx - 8} ry={ry - 12} fill={dragonTint} stroke="#1a1208" strokeWidth="0.6" />
          {/* Eyes — inset from horizontal mid */}
          <circle cx={cx - 8} cy={cy - 10} r="2.2" fill="#fffcde" />
          <circle cx={cx + 8} cy={cy - 10} r="2.2" fill="#fffcde" />
          <circle cx={cx - 8} cy={cy - 10} r="0.9" fill="#1a1208" />
          <circle cx={cx + 8} cy={cy - 10} r="0.9" fill="#1a1208" />

          {/* Platform-specific accent */}
          {platform === 'mastodon' && (
            // Tusks — two small triangles below the eyes.
            <g fill="#fffcde" stroke="#1a1208" strokeWidth="0.4">
              <polygon points={`${cx - 4},${cy + 6} ${cx - 3},${cy + 12} ${cx - 5},${cy + 10}`} />
              <polygon points={`${cx + 4},${cy + 6} ${cx + 3},${cy + 12} ${cx + 5},${cy + 10}`} />
            </g>
          )}

          {platform === 'bluesky' && (
            // Butterfly wings — two translucent ellipses behind the body.
            <g opacity="0.6">
              <ellipse cx={cx - rx + 6} cy={cy} rx="14" ry="22" fill="#a8d8e8" />
              <ellipse cx={cx + rx - 6} cy={cy} rx="14" ry="22" fill="#a8d8e8" />
            </g>
          )}

          {platform === 'reddit' && (
            // Three scaled ridges along the back.
            <g fill="#fffcde" opacity="0.7">
              <path d={`M ${cx - 6} ${cy + 4} q 6 -6 12 0`} stroke="#1a1208" strokeWidth="0.4" fill="none" />
              <path d={`M ${cx - 6} ${cy + 12} q 6 -6 12 0`} stroke="#1a1208" strokeWidth="0.4" fill="none" />
              <path d={`M ${cx - 6} ${cy + 20} q 6 -6 12 0`} stroke="#1a1208" strokeWidth="0.4" fill="none" />
            </g>
          )}
        </g>
      )}

      {/* Reduced-motion gate: animation only fires when the user
          hasn't asked for less of it. The selectors target the
          nested classes above. */}
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .egg-art-glow {
            animation: egg-glow-pulse 3s ease-in-out infinite;
            transform-origin: center;
          }
          .egg-art-${status === 'hatching' ? 'hatching' : 'NA'} .egg-art-glow {
            animation-duration: 1.2s;
          }
          .egg-art-cracks {
            animation: egg-cracks-shimmer 4s ease-in-out infinite;
          }
          @keyframes egg-glow-pulse {
            0%, 100% { opacity: 0.6; }
            50%      { opacity: 1; }
          }
          @keyframes egg-cracks-shimmer {
            0%, 100% { opacity: 1; }
            50%      { opacity: 0.7; }
          }
        }
      `}</style>
    </svg>
  );
}
