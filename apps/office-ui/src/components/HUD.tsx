'use client';

import type { FC } from 'react';

interface HUDProps {
  activeAgentCount: number;
  pendingApprovalCount: number;
  computeTokens?: { used: number; limit: number };
  colyseusConnected: boolean;
  approvalsConnected: boolean;
}

export const HUD: FC<HUDProps> = ({
  activeAgentCount,
  pendingApprovalCount,
  computeTokens,
  colyseusConnected,
  approvalsConnected,
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
        <p className="pixel-text mt-1 text-lg text-cyan-400">{activeAgentCount}</p>
      </div>

      {/* Right: Pending Approvals + Connection Status */}
      <div className="pointer-events-auto flex flex-col gap-2">
        <div className="retro-panel relative px-4 py-3 font-mono">
          <span className="pixel-text text-[8px] uppercase text-slate-400">
            Approvals
          </span>
          <p className="pixel-text mt-1 text-lg text-amber-400">
            {pendingApprovalCount}
          </p>
          {pendingApprovalCount > 0 && (
            <span
              className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center bg-red-600 pixel-text text-[7px] text-white shadow-[0_0_0_2px_#000]"
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

        {/* Minimap placeholder */}
        <div className="retro-panel flex h-24 w-32 items-center justify-center">
          <span className="pixel-text text-[7px] text-slate-600">MINIMAP</span>
        </div>
      </div>
    </div>
  );
};
