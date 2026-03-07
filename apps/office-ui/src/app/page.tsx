'use client';

import dynamic from 'next/dynamic';
import { HUD } from '@/components/HUD';
import { DashboardPanel } from '@/components/DashboardPanel';
import { ChatPanel } from '@/components/ChatPanel';
import { EmotePicker } from '@/components/EmotePicker';
import { AvatarEditor } from '@/components/AvatarEditor';
import { CoWebsitePanel } from '@/components/CoWebsitePanel';
import { PopupOverlay } from '@/components/PopupOverlay';
import { useApprovals } from '@/hooks/useApprovals';
import { useColyseus } from '@/hooks/useColyseus';
import type { PlayerEmoteEvent } from '@/hooks/useColyseus';
import { useAvatarConfig } from '@/hooks/useAvatarConfig';
import { useState, useCallback, useRef, useEffect } from 'react';
import { ApprovalModal } from '@autoswarm/ui';
import type { CoWebsiteEvent, PopupEvent } from '@/game/PhaserGame';
import type { ApprovalRequest, AvatarConfig } from '@autoswarm/shared-types';

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
  // Lazy-load gameEventBus ref to bridge emote events to Phaser
  const gameEventBusRef = useRef<{ emit: (event: string, detail: unknown) => void } | null>(null);
  useEffect(() => {
    import('@/game/PhaserGame').then((mod) => {
      gameEventBusRef.current = mod.gameEventBus;
    });
  }, []);

  const handlePlayerEmote = useCallback((event: PlayerEmoteEvent) => {
    gameEventBusRef.current?.emit('player-emote', event);
  }, []);

  const {
    officeState,
    connected: colyseusConnected,
    sessionId,
    sendMove,
    sendChat,
    sendEmote,
    sendAvatarConfig,
  } = useColyseus({ playerName: 'Tactician', onPlayerEmote: handlePlayerEmote });
  const {
    pendingApprovals,
    approve,
    deny,
    connected: approvalsConnected,
  } = useApprovals();
  const { config: avatarConfig, saveConfig: saveAvatarConfig, isFirstVisit } = useAvatarConfig();
  const [avatarEditorOpen, setAvatarEditorOpen] = useState(false);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(
    null,
  );
  const [coWebsite, setCoWebsite] = useState<CoWebsiteEvent | null>(null);
  const [popup, setPopup] = useState<PopupEvent | null>(null);

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

  const handleEmote = useCallback(
    (type: string) => {
      sendEmote(type);
    },
    [sendEmote],
  );

  const handleCoWebsite = useCallback(
    (event: CoWebsiteEvent) => {
      setCoWebsite(event);
    },
    [],
  );

  const handlePopup = useCallback(
    (event: PopupEvent) => {
      setPopup(event);
    },
    [],
  );

  const handleAvatarSave = useCallback(
    (config: AvatarConfig) => {
      saveAvatarConfig(config);
      sendAvatarConfig(JSON.stringify(config));
      setAvatarEditorOpen(false);
      // Forward avatar config to Phaser
      gameEventBusRef.current?.emit('avatar-config', config);
    },
    [saveAvatarConfig, sendAvatarConfig],
  );

  // Open avatar editor on first visit
  useEffect(() => {
    if (isFirstVisit && colyseusConnected) {
      setAvatarEditorOpen(true);
    }
  }, [isFirstVisit, colyseusConnected]);

  // Send avatar config to server when connected
  useEffect(() => {
    if (colyseusConnected && avatarConfig) {
      sendAvatarConfig(JSON.stringify(avatarConfig));
      gameEventBusRef.current?.emit('avatar-config', avatarConfig);
    }
  }, [colyseusConnected, avatarConfig, sendAvatarConfig]);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-slate-900">
      <PhaserGame
        onApprovalOpen={handleApprovalOpen}
        officeState={officeState}
        sessionId={sessionId}
        onPlayerMove={handlePlayerMove}
        onEmote={handleEmote}
        onCoWebsite={handleCoWebsite}
        onPopup={handlePopup}
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

      <EmotePicker onEmote={handleEmote} />

      <AvatarEditor
        open={avatarEditorOpen}
        initialConfig={avatarConfig}
        onSave={handleAvatarSave}
        onClose={() => setAvatarEditorOpen(false)}
      />

      <button
        onClick={() => setAvatarEditorOpen(true)}
        className="absolute top-4 right-4 z-20 rounded bg-slate-800/90 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
      >
        Avatar
      </button>

      <CoWebsitePanel
        url={coWebsite?.url ?? null}
        title={coWebsite?.title ?? ''}
        onClose={() => setCoWebsite(null)}
      />

      <PopupOverlay
        open={!!popup}
        title={popup?.title ?? ''}
        content={popup?.content ?? ''}
        onClose={() => setPopup(null)}
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
