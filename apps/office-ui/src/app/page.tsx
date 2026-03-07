'use client';

import dynamic from 'next/dynamic';
import { HUD } from '@/components/HUD';
import { DashboardPanel } from '@/components/DashboardPanel';
import { ChatPanel } from '@/components/ChatPanel';
import { useApprovals } from '@/hooks/useApprovals';
import { useColyseus } from '@/hooks/useColyseus';
import { useState, useCallback } from 'react';
import { ApprovalModal } from '@autoswarm/ui';
import type { ApprovalRequest } from '@autoswarm/shared-types';

const PhaserGame = dynamic(() => import('@/game/PhaserGame'), {
  ssr: false,
  loading: () => (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-900">
      <div className="pixel-text text-center">
        <p className="mb-4 text-lg text-indigo-400">LOADING</p>
        <div className="mx-auto h-2 w-48 bg-slate-800 pixel-border">
          <div className="h-full w-1/2 animate-pulse bg-indigo-500" />
        </div>
      </div>
    </div>
  ),
});

export default function HomePage() {
  const {
    officeState,
    connected: colyseusConnected,
    sessionId,
    sendMove,
    sendChat,
  } = useColyseus('Tactician');
  const {
    pendingApprovals,
    approve,
    deny,
    connected: approvalsConnected,
  } = useApprovals();
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(
    null,
  );

  const handleApprovalOpen = useCallback(
    (agentId: string) => {
      const request = pendingApprovals.find((a) => a.agentId === agentId);
      if (request) {
        setActiveApproval(request);
      }
    },
    [pendingApprovals],
  );

  const handleApprove = useCallback(
    (requestId: string, feedback: string) => {
      approve(requestId, feedback || undefined);
      setActiveApproval(null);
    },
    [approve],
  );

  const handleDeny = useCallback(
    (requestId: string, feedback: string) => {
      deny(requestId, feedback || undefined);
      setActiveApproval(null);
    },
    [deny],
  );

  const handlePlayerMove = useCallback(
    (x: number, y: number) => {
      sendMove(x, y);
    },
    [sendMove],
  );

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-slate-900">
      <PhaserGame
        onApprovalOpen={handleApprovalOpen}
        officeState={officeState}
        sessionId={sessionId}
        onPlayerMove={handlePlayerMove}
      />

      <HUD
        activeAgentCount={officeState?.activeAgentCount ?? 0}
        pendingApprovalCount={pendingApprovals.length}
        computeTokens={officeState ? { used: 0, limit: 10000 } : undefined}
        colyseusConnected={colyseusConnected}
        approvalsConnected={approvalsConnected}
      />

      <DashboardPanel
        open={dashboardOpen}
        onToggle={() => setDashboardOpen((prev) => !prev)}
        departments={officeState?.departments ?? []}
      />

      <ChatPanel
        messages={officeState?.chatMessages ?? []}
        onSend={sendChat}
        localSessionId={sessionId ?? ''}
      />

      {activeApproval && (
        <ApprovalModal
          open={!!activeApproval}
          onOpenChange={(open) => {
            if (!open) setActiveApproval(null);
          }}
          request={activeApproval}
          onApprove={handleApprove}
          onDeny={handleDeny}
        />
      )}
    </main>
  );
}
