'use client';

import { useRef, useEffect, type FC } from 'react';
import type { Department } from '@autoswarm/shared-types';

interface HUDProps {
  activeAgentCount: number;
  pendingApprovalCount: number;
  computeTokens?: { used: number; limit: number };
  colyseusConnected: boolean;
  approvalsConnected: boolean;
  departments?: Department[];
  playerPosition?: { x: number; y: number } | null;
}

const WORLD_WIDTH = 1280;
const WORLD_HEIGHT = 704;
const MINIMAP_W = 128;
const MINIMAP_H = 96;

const DEPT_COLORS: Record<string, string> = {
  engineering: '#1e3a5f',
  sales: '#3b1e5f',
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

function Minimap({ departments, playerPosition }: { departments: Department[]; playerPosition: { x: number; y: number } | null }) {
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
      engineering: { x: 96, y: 80, w: 192, h: 160 },
      sales: { x: 480, y: 80, w: 192, h: 160 },
      support: { x: 96, y: 400, w: 192, h: 160 },
      research: { x: 480, y: 400, w: 192, h: 160 },
    };

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
        ctx.fillStyle = ROLE_COLORS[dept.agents[i].role] ?? '#94a3b8';
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

export const HUD: FC<HUDProps> = ({
  activeAgentCount,
  pendingApprovalCount,
  computeTokens,
  colyseusConnected,
  approvalsConnected,
  departments = [],
  playerPosition = null,
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
      className="pointer-events-none absolute left-0 right-0 top-0 z-hud flex items-start justify-between p-4"
      role="status"
      aria-label="Game HUD"
    >
      {/* Left: Compute Token Bar */}
      <div className="pointer-events-auto retro-panel px-4 py-3 font-mono">
        <div className="mb-1 flex items-center gap-2">
          <span className="pixel-text text-[8px] uppercase text-slate-400">
            Compute Tokens
          </span>
        </div>
        <div className="mb-1 h-3 w-48 bg-slate-900 pixel-border">
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
        <div className="flex justify-between text-[9px] text-slate-500">
          <span>{computeTokens?.used.toLocaleString() ?? 0}</span>
          <span>{computeTokens?.limit.toLocaleString() ?? 10000}</span>
        </div>
      </div>

      {/* Center: Agent Count */}
      <div className="pointer-events-auto retro-panel px-4 py-3 text-center font-mono">
        <span className="pixel-text text-[8px] uppercase text-slate-400">
          Active Agents
        </span>
        <p className="pixel-text mt-1 text-lg text-cyan-400">
          <span key={activeAgentCount} className="inline-block animate-pop-in">
            {activeAgentCount}
          </span>
        </p>
      </div>

      {/* Right: Pending Approvals + Connection Status */}
      <div className="pointer-events-auto flex flex-col gap-2">
        <div className="retro-panel relative px-4 py-3 font-mono">
          <span className="pixel-text text-[8px] uppercase text-slate-400">
            Approvals
          </span>
          <p className="pixel-text mt-1 text-lg text-amber-400">
            <span key={pendingApprovalCount} className="inline-block animate-pop-in">
              {pendingApprovalCount}
            </span>
          </p>
          {pendingApprovalCount > 0 && (
            <span
              className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center bg-red-600 pixel-text text-[7px] text-white shadow-[0_0_0_2px_#000] animate-pulse animate-pulse-border"
              aria-label={`${pendingApprovalCount} pending approvals`}
            >
              {pendingApprovalCount > 9 ? '9+' : pendingApprovalCount}
            </span>
          )}
        </div>

        {/* Connection indicators */}
        <div className="retro-panel px-3 py-2 font-mono text-[8px]">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                colyseusConnected ? 'bg-emerald-400' : 'bg-red-500 animate-pulse'
              }`}
            />
            <span className="text-slate-400">Room</span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                approvalsConnected ? 'bg-emerald-400' : 'bg-red-500 animate-pulse'
              }`}
            />
            <span className="text-slate-400">API</span>
          </div>
        </div>

        {/* Minimap */}
        <div className="retro-panel overflow-hidden" style={{ width: MINIMAP_W + 8, height: MINIMAP_H + 8, padding: 4 }}>
          <Minimap departments={departments} playerPosition={playerPosition} />
        </div>
      </div>
    </div>
  );
};
