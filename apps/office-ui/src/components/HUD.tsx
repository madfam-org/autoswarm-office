'use client';

import { memo, useRef, useEffect, type FC } from 'react';
import type { Department } from '@selva/shared-types';

/**
 * Player position changes faster than 4px (one minimap pixel at default scale)
 * are visually indistinguishable on the minimap. Skipping re-renders below this
 * threshold reduces canvas redraws from ~15Hz (player-move event rate) to
 * roughly the rate at which the player visibly moves across the minimap.
 */
const MINIMAP_POSITION_REDRAW_THRESHOLD_PX = 4;

interface HUDProps {
  activeAgentCount: number;
  pendingApprovalCount: number;
  computeTokens?: { used: number; limit: number };
  colyseusConnected: boolean;
  approvalsConnected: boolean;
  departments?: Department[];
  playerPosition?: { x: number; y: number } | null;
  userName?: string | null;
  onApprovalClick?: () => void;
  followingPlayer?: string | null;
  explorerMode?: boolean;
  viewMode?: 'game' | 'simple';
  onToggleViewMode?: () => void;
}

const WORLD_WIDTH = 1600;
const WORLD_HEIGHT = 896;
const MINIMAP_W = 160;
const MINIMAP_H = 90;

const DEPT_COLORS: Record<string, string> = {
  engineering: '#1e3a5f',
  crm: '#3b1e5f',
  support: '#1e5f3a',
  research: '#5f3a1e',
};

const ROLE_COLORS: Record<string, string> = {
  planner: '#8b5cf6',
  coder: '#06b6d4',
  reviewer: '#f59e0b',
  researcher: '#10b981',
  crm: '#f43f5e',
  support: '#0ea5e9',
};

const STATUS_COLORS: Record<string, string> = {
  idle: '#94a3b8',
  working: '#06b6d4',
  waiting_approval: '#fbbf24',
  paused: '#a78bfa',
  error: '#ef4444',
};

interface MinimapProps {
  departments: Department[];
  playerPosition: { x: number; y: number } | null;
}

function MinimapInner({ departments, playerPosition }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, MINIMAP_W, MINIMAP_H);

    const scaleX = MINIMAP_W / WORLD_WIDTH;
    const scaleY = MINIMAP_H / WORLD_HEIGHT;

    // Draw department zones
    const DEPT_LAYOUT: Record<string, { x: number; y: number; w: number; h: number }> = {
      engineering: { x: 32, y: 32, w: 640, h: 320 },
      crm: { x: 928, y: 32, w: 640, h: 320 },
      support: { x: 32, y: 544, w: 640, h: 320 },
      research: { x: 928, y: 544, w: 640, h: 320 },
    };

    // Draw room outlines (wall borders)
    ctx.strokeStyle = '#475569';
    ctx.lineWidth = 1;
    for (const layout of Object.values(DEPT_LAYOUT)) {
      ctx.strokeRect(layout.x * scaleX, layout.y * scaleY, layout.w * scaleX, layout.h * scaleY);
    }

    // Draw corridors as lighter background
    ctx.fillStyle = '#1e293b';
    ctx.globalAlpha = 0.4;
    // Horizontal corridor
    ctx.fillRect(0, 12 * 32 * scaleY, MINIMAP_W, 4 * 32 * scaleY);
    // Vertical corridor
    ctx.fillRect(22 * 32 * scaleX, 0, 6 * 32 * scaleX, MINIMAP_H);
    ctx.globalAlpha = 1;

    for (const dept of departments) {
      const layout = DEPT_LAYOUT[dept.slug];
      if (!layout) continue;
      ctx.fillStyle = DEPT_COLORS[dept.slug] ?? '#334155';
      ctx.globalAlpha = 0.5;
      ctx.fillRect(layout.x * scaleX, layout.y * scaleY, layout.w * scaleX, layout.h * scaleY);
      ctx.globalAlpha = 1;

      // Agent dots
      for (let i = 0; i < dept.agents.length; i++) {
        const col = i % 3;
        const row = Math.floor(i / 3);
        const ax = (layout.x + 48 + col * 48) * scaleX;
        const ay = (layout.y + 48 + row * 48) * scaleY;
        const agent = dept.agents[i];
        ctx.fillStyle = STATUS_COLORS[agent.status] ?? '#94a3b8';
        ctx.fillRect(ax - 1, ay - 1, 2, 2);
      }
    }

    // Player dot (pulsing via size alternation handled by re-render)
    if (playerPosition) {
      const px = playerPosition.x * scaleX;
      const py = playerPosition.y * scaleY;
      ctx.fillStyle = '#818cf8';
      ctx.fillRect(px - 1.5, py - 1.5, 3, 3);
      // Glow ring
      ctx.strokeStyle = '#818cf8';
      ctx.globalAlpha = 0.4;
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }, [departments, playerPosition]);

  return (
    <canvas
      ref={canvasRef}
      width={MINIMAP_W}
      height={MINIMAP_H}
      className="block"
      style={{ imageRendering: 'pixelated' }}
    />
  );
}

/**
 * Memoised Minimap. The canvas redraws on every prop change, so we want to
 * skip re-renders when the change is visually imperceptible. Departments are
 * compared by reference (the parent re-creates the array on state changes,
 * but it's stable across position updates). Player position changes smaller
 * than {@link MINIMAP_POSITION_REDRAW_THRESHOLD_PX} are ignored — at the
 * default minimap scale (160x90 over 1600x896) one minimap pixel is roughly
 * 10 world px on the X axis and 10 world px on the Y axis, so 4px is well
 * under one pixel of visible movement and saves >70% of redraws.
 */
const Minimap = memo(MinimapInner, (prev, next) => {
  if (prev.departments !== next.departments) return false;
  const a = prev.playerPosition;
  const b = next.playerPosition;
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    Math.abs(a.x - b.x) < MINIMAP_POSITION_REDRAW_THRESHOLD_PX &&
    Math.abs(a.y - b.y) < MINIMAP_POSITION_REDRAW_THRESHOLD_PX
  );
});

export const HUD: FC<HUDProps> = ({
  activeAgentCount,
  pendingApprovalCount,
  computeTokens,
  colyseusConnected,
  approvalsConnected,
  departments = [],
  playerPosition = null,
  userName = null,
  onApprovalClick,
  followingPlayer = null,
  explorerMode = false,
  viewMode = 'game',
  onToggleViewMode,
}) => {
  const tokenPercent = computeTokens
    ? Math.min((computeTokens.used / computeTokens.limit) * 100, 100)
    : 0;

  const tokenBarColor =
    tokenPercent > 80
      ? 'bg-red-500'
      : tokenPercent > 50
        ? 'bg-amber-500'
        : 'bg-emerald-500';

  return (
    <div
      className="pointer-events-none absolute left-0 right-0 top-0 z-hud flex items-start justify-between gap-1 p-2 sm:gap-2 sm:p-4"
      role="status"
      aria-label="Game HUD"
    >
      {/* Left: Compute Token Bar + User Identity */}
      <div className="pointer-events-auto flex flex-col gap-1 sm:gap-2 min-w-0">
        <div className="retro-panel px-2 py-2 sm:px-4 sm:py-3 font-mono">
          <div className="mb-1 hidden sm:flex items-center gap-2">
            <span className="pixel-text text-[8px] uppercase text-slate-400">
              Compute Tokens
            </span>
          </div>
          <div className="mb-1 h-2 sm:h-3 w-24 sm:w-48 bg-slate-900 pixel-border">
            <div
              className={`h-full transition-all duration-300 ${tokenBarColor}`}
              style={{ width: `${tokenPercent}%` }}
              role="progressbar"
              aria-valuenow={computeTokens?.used ?? 0}
              aria-valuemin={0}
              aria-valuemax={computeTokens?.limit ?? 10000}
              aria-label="Compute token usage"
            />
          </div>
          <div className="hidden sm:flex justify-between text-[9px] text-slate-500">
            <span>{computeTokens?.used.toLocaleString() ?? 0}</span>
            <span>{computeTokens?.limit.toLocaleString() ?? 10000}</span>
          </div>
        </div>
        {userName && (
          <div className="hidden sm:block retro-panel px-3 py-1.5 font-mono text-[8px] text-slate-400">
            <span className="text-indigo-400">{userName}</span>
          </div>
        )}
        {onToggleViewMode && (
          <button
            onClick={onToggleViewMode}
            className="hidden sm:block retro-panel retro-btn px-3 py-1.5 font-mono text-[8px] text-slate-300 transition-colors hover:text-white"
            aria-label={viewMode === 'game' ? 'Switch to simple view' : 'Switch to game view'}
          >
            {viewMode === 'game' ? 'Simple View' : 'Game View'}
          </button>
        )}
      </div>

      {/* Center: Agent Count + Status Badges */}
      <div className="pointer-events-auto flex flex-col items-center gap-1 sm:gap-2">
        {followingPlayer && (
          <div className="retro-panel px-2 py-1 sm:px-3 sm:py-1.5 font-mono text-[7px] sm:text-[8px] text-emerald-400 animate-fade-in">
            <span className="hidden sm:inline">Following: </span>{followingPlayer} <span className="text-slate-500">[ESC]</span>
          </div>
        )}
        {explorerMode && (
          <div className="retro-panel px-2 py-1 sm:px-3 sm:py-1.5 font-mono text-[7px] sm:text-[8px] text-indigo-400 animate-fade-in">
            <span className="hidden sm:inline">EXPLORER MODE </span>
            <span className="sm:hidden">EXPLORE </span>
            <span className="text-slate-500">[Tab/ESC]</span>
          </div>
        )}
      </div>

      {/* Agent Count */}
      <div className="pointer-events-auto retro-panel px-2 py-2 sm:px-4 sm:py-3 text-center font-mono">
        <span className="pixel-text text-[7px] sm:text-[8px] uppercase text-slate-400">
          <span className="hidden sm:inline">Active Agents</span>
          <span className="sm:hidden" aria-hidden="true">Agents</span>
        </span>
        <p className="pixel-text mt-0.5 sm:mt-1 text-sm sm:text-lg text-cyan-400">
          <span key={activeAgentCount} className="inline-block animate-pop-in">
            {activeAgentCount}
          </span>
        </p>
      </div>

      {/* Right: Pending Approvals + Connection Status */}
      <div className="pointer-events-auto flex flex-col gap-1 sm:gap-2">
        <button
          className="retro-panel relative px-2 py-2 sm:px-4 sm:py-3 font-mono cursor-pointer hover:bg-slate-700/50 transition-colors"
          onClick={onApprovalClick}
          aria-label={`Open approval queue (${pendingApprovalCount} pending)`}
        >
          <span className="pixel-text text-[7px] sm:text-[8px] uppercase text-slate-400">
            <span className="hidden xs:inline">Approvals</span>
            <span className="xs:hidden" aria-hidden="true">Aprv</span>
          </span>
          <p className="pixel-text mt-0.5 sm:mt-1 text-sm sm:text-lg text-amber-400">
            <span key={pendingApprovalCount} className="inline-block animate-pop-in">
              {pendingApprovalCount}
            </span>
          </p>
          {pendingApprovalCount > 0 && (
            <span
              className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center bg-red-600 pixel-text text-[7px] text-white shadow-[0_0_0_2px_#000] animate-pulse animate-pulse-border"
              aria-label={`${pendingApprovalCount} pending approvals`}
              aria-live="polite"
              role="status"
            >
              {pendingApprovalCount > 9 ? '9+' : pendingApprovalCount}
            </span>
          )}
        </button>

        {/* Connection indicators */}
        <div
          className="hidden sm:block retro-panel px-3 py-2 font-mono text-[8px]"
          role="group"
          aria-label="Connection status"
        >
          <div
            className="flex items-center gap-2"
            title={`Room: ${colyseusConnected ? 'connected' : 'disconnected'}`}
          >
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                colyseusConnected ? 'bg-emerald-400' : 'bg-red-500 animate-pulse'
              }`}
              aria-hidden="true"
            />
            <span className="text-slate-400">Room</span>
            <span className="sr-only">
              {colyseusConnected ? 'connected' : 'disconnected'}
            </span>
          </div>
          <div
            className="mt-1 flex items-center gap-2"
            title={`API: ${approvalsConnected ? 'connected' : 'disconnected'}`}
          >
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                approvalsConnected ? 'bg-emerald-400' : 'bg-red-500 animate-pulse'
              }`}
              aria-hidden="true"
            />
            <span className="text-slate-400">API</span>
            <span className="sr-only">
              {approvalsConnected ? 'connected' : 'disconnected'}
            </span>
          </div>
        </div>

        {/* Minimap — only render when there are departments to show */}
        {departments.length > 0 && (
          <div className="hidden lg:block retro-panel overflow-hidden" style={{ width: MINIMAP_W + 8, height: MINIMAP_H + 8, padding: 4 }}>
            <Minimap departments={departments} playerPosition={playerPosition} />
          </div>
        )}
      </div>
    </div>
  );
};
