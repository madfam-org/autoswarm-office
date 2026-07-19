'use client';

import dynamic from 'next/dynamic';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { ToastProvider } from '@/components/Toast';
import { HUD } from '@/components/HUD';
import { DashboardPanel } from '@/components/DashboardPanel';
import { TaskDispatchPanel } from '@/components/TaskDispatchPanel';
import { ApprovalPanel } from '@/components/ApprovalPanel';
import { ChatPanel } from '@/components/ChatPanel';
import { EmotePicker } from '@/components/EmotePicker';
import { AvatarEditor } from '@/components/AvatarEditor';
import { CoWebsitePanel } from '@/components/CoWebsitePanel';
import { PopupOverlay } from '@/components/PopupOverlay';
import { SkillMarketplace } from '@/components/SkillMarketplace';
import { CampaignDashboard } from '@/components/campaigns/CampaignDashboard';
import { CalendarPanel } from '@/components/CalendarPanel';
import { WhiteboardPanel } from '@/components/WhiteboardPanel';
import { DeskInfoPanel } from '@/components/DeskInfoPanel';
import { VideoOverlay } from '@/components/VideoOverlay';
import { MediaControls } from '@/components/MediaControls';
import { RecordingControls } from '@/components/RecordingControls';
import { MeetingNotesPanel } from '@/components/MeetingNotesPanel';
import { DemoBanner } from '@/components/DemoBanner';
import { useLocalStorageState } from '@/hooks/useLocalStorageState';
import { useApprovals } from '@/hooks/useApprovals';
import { useTaskDispatch } from '@/hooks/useTaskDispatch';
import { useCalendar } from '@/hooks/useCalendar';
import { useMeetingNotes } from '@/hooks/useMeetingNotes';
import { useColyseus } from '@/hooks/useColyseus';
import { useComputeTokens } from '@/hooks/useComputeTokens';
import type { PlayerEmoteEvent, ProximityUpdate, WebRTCSignal, SpotlightActiveEvent, LiveKitCredentialsEvent } from '@/hooks/useColyseus';
import type { LiveKitCredentials } from '@/hooks/useProximityVideo';
import { useAvatarConfig } from '@/hooks/useAvatarConfig';
import { usePlayerStatus } from '@/hooks/usePlayerStatus';
import { StatusSelector } from '@/components/StatusSelector';
import { MusicStatus } from '@/components/MusicStatus';
import { useProximityVideo } from '@/hooks/useProximityVideo';
import { useRecording } from '@/hooks/useRecording';
import { useWhiteboard } from '@/hooks/useWhiteboard';
import { useSpotlight } from '@/hooks/useSpotlight';
import { useNotifications } from '@/hooks/useNotifications';
import { MobileNav } from '@/components/MobileNav';
import { AtriumOverlay } from '@/components/atrium/AtriumOverlay';
import { MegaphoneControls } from '@/components/MegaphoneControls';
import { SpotlightControls } from '@/components/SpotlightControls';
import { SpotlightView } from '@/components/SpotlightView';
import { RoomNavigator } from '@/components/RoomNavigator';
import { SimplifiedView } from '@/components/SimplifiedView';
import { OpsFeed } from '@/components/OpsFeed';
import { MetricsDashboard } from '@/components/MetricsDashboard';
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { ApprovalModal } from '@selva/ui';
import type { CoWebsiteEvent, PopupEvent } from '@/game/PhaserGame';
import type { ApprovalRequest, AvatarConfig, CompanionType } from '@selva/shared-types';
import { getSessionUser } from '@/lib/api';

const WorkflowEditor = dynamic(
  () => import('@/components/workflow-editor/WorkflowEditor').then((m) => ({ default: m.WorkflowEditor })),
  { ssr: false },
);

const MapEditor = dynamic(
  () => import('@/components/map-editor/MapEditor').then((m) => ({ default: m.MapEditor })),
  { ssr: false },
);

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

export interface OfficeExperienceProps {
  mode: 'live' | 'demo';
}

export function OfficeExperience({ mode }: OfficeExperienceProps) {
  const isDemo = mode === 'demo';

  // Real daily compute-token usage for the HUD meter (disabled in demo,
  // which has no billing). Replaces the old hardcoded {used:0, limit:10000}.
  const computeTokens = useComputeTokens(!isDemo);

  // Lazy-load gameEventBus ref to bridge emote events to Phaser. The actual
  // import + listener wiring is consolidated into one useEffect lower in this
  // component (search for "consolidated PhaserGame loader") to avoid 5
  // separate dynamic imports racing on cleanup.
  const gameEventBusRef = useRef<{ emit: (event: string, detail: unknown) => void } | null>(null);

  const handlePlayerEmote = useCallback((event: PlayerEmoteEvent) => {
    gameEventBusRef.current?.emit('player-emote', event);
  }, []);

  // Refs for bridging proximity video callbacks (breaks circular dep between hooks)
  const proximityUpdateRef = useRef<(update: ProximityUpdate) => void>(() => {});
  const webrtcSignalRef = useRef<(signal: WebRTCSignal) => void>(() => {});
  const spotlightActiveRef = useRef<(event: SpotlightActiveEvent) => void>(() => {});

  const handleProximityUpdate = useCallback((update: ProximityUpdate) => {
    proximityUpdateRef.current(update);
  }, []);

  const handleWebRTCSignal = useCallback((signal: WebRTCSignal) => {
    webrtcSignalRef.current(signal);
  }, []);

  const handleSpotlightActive = useCallback((event: SpotlightActiveEvent) => {
    spotlightActiveRef.current(event);
  }, []);

  // LiveKit SFU credentials received from Colyseus
  const [liveKitCredentials, setLiveKitCredentials] = useState<LiveKitCredentials | null>(null);
  const handleLiveKitCredentials = useCallback((creds: LiveKitCredentialsEvent) => {
    setLiveKitCredentials({ url: creds.url, token: creds.token });
  }, []);

  const sessionUser = useMemo(() => getSessionUser(), []);

  const {
    room: colyseusRoom,
    officeState,
    connected: colyseusConnected,
    sessionId,
    sendMove,
    sendChat,
    sendEmote,
    sendAvatarConfig,
    sendStatus,
    sendSignal,
    sendCompanion,
    sendMusicStatus,
    sendMegaphoneStart,
    sendMegaphoneStop,
    sendSpotlightStart,
    sendSpotlightStop,
    sendLockBubble,
    sendUnlockBubble,
  } = useColyseus({
    playerName: sessionUser?.name ?? sessionUser?.email ?? 'Tactician',
    onPlayerEmote: handlePlayerEmote,
    onProximityUpdate: handleProximityUpdate,
    onWebRTCSignal: handleWebRTCSignal,
    onSpotlightActive: handleSpotlightActive,
    onLiveKitCredentials: handleLiveKitCredentials,
  });

  const { status: playerStatus, changeStatus: changePlayerStatus } = usePlayerStatus({
    sendStatus,
    enabled: colyseusConnected,
  });

  // Desktop notifications for chat messages when tab is unfocused
  useNotifications(
    sessionUser?.name ?? sessionUser?.email ?? 'Tactician',
    playerStatus
  );

  const {
    peers,
    localStream,
    audioEnabled,
    videoEnabled,
    screenSharing,
    noiseSuppression,
    screenShareQuality,
    setScreenShareQuality,
    toggleAudio,
    toggleVideo,
    toggleScreenShare,
    toggleNoiseSuppression,
    handleProximityUpdate: videoHandleProximity,
    handleWebRTCSignal: videoHandleSignal,
  } = useProximityVideo({
    localSessionId: sessionId,
    sendSignal,
    enabled: colyseusConnected,
    playerStatus,
    liveKitCredentials,
  });

  const {
    recordingState,
    formattedDuration,
    lastRecordingUrl,
    startRecording,
    stopRecording,
  } = useRecording({ localStream, peers });

  const {
    strokes: whiteboardStrokes,
    tool: whiteboardTool,
    color: whiteboardColor,
    width: whiteboardWidth,
    colors: whiteboardColors,
    widths: whiteboardWidths,
    sendStroke: whiteboardSendStroke,
    clearBoard: whiteboardClear,
    setTool: whiteboardSetTool,
    setColor: whiteboardSetColor,
    setWidth: whiteboardSetWidth,
  } = useWhiteboard({ room: colyseusConnected ? colyseusRoom : null });

  const {
    active: spotlightActive,
    isPresenting: spotlightIsPresenting,
    presenterName: spotlightPresenterName,
    presenterSessionId: spotlightPresenterSessionId,
    startSpotlight,
    stopSpotlight,
    handleSpotlightActive: spotlightHandleActive,
  } = useSpotlight({
    localSessionId: sessionId,
    sendSpotlightStart,
    sendSpotlightStop,
    enabled: colyseusConnected,
  });

  const {
    status: meetingNotesStatus,
    notes: meetingNotes,
    error: meetingNotesError,
    dispatchMeetingNotes,
    reset: resetMeetingNotes,
  } = useMeetingNotes();

  // Wire up the refs in an effect (not during render) so React's concurrent
  // mode does not desync them when a render is interrupted and replayed.
  // Assigning during the render body would bind the ref to the in-flight
  // closures even if React throws away the render, leaving callers with
  // stale handlers.
  useEffect(() => {
    proximityUpdateRef.current = videoHandleProximity;
  });
  useEffect(() => {
    webrtcSignalRef.current = videoHandleSignal;
  });
  useEffect(() => {
    spotlightActiveRef.current = spotlightHandleActive;
  });
  const {
    pendingApprovals,
    approve,
    deny,
    connected: approvalsConnected,
  } = useApprovals();
  const {
    dispatch: dispatchTask,
    status: dispatchStatus,
    error: dispatchError,
    lastDispatchedTask,
    reset: resetDispatch,
  } = useTaskDispatch();
  const {
    events: calendarEvents,
    isBusy: calendarBusy,
    connected: calendarConnected,
    status: calendarStatus,
    error: calendarError,
    connect: connectCalendar,
    disconnect: disconnectCalendar,
    refresh: refreshCalendar,
  } = useCalendar({
    onBusyChange: useCallback((busy: boolean) => {
      if (busy && colyseusConnected) {
        changePlayerStatus('busy');
      }
    }, [colyseusConnected, changePlayerStatus]),
  });
  const { config: avatarConfig, saveConfig: saveAvatarConfig, isFirstVisit } = useAvatarConfig();
  const [avatarEditorOpen, setAvatarEditorOpen] = useState(false);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [dispatchPanelOpen, setDispatchPanelOpen] = useState(false);
  const [approvalPanelOpen, setApprovalPanelOpen] = useState(false);
  const [workflowEditorOpen, setWorkflowEditorOpen] = useState(false);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);
  const [campaignDashboardOpen, setCampaignDashboardOpen] = useState(false);
  const [whiteboardOpen, setWhiteboardOpen] = useState(false);
  const [mapEditorOpen, setMapEditorOpen] = useState(false);
  const [calendarPanelOpen, setCalendarPanelOpen] = useState(false);
  const [meetingNotesPanelOpen, setMeetingNotesPanelOpen] = useState(false);
  const [opsFeedOpen, setOpsFeedOpen] = useState(false);
  const [chatForceCollapsed, setChatForceCollapsed] = useState(false);
  const [metricsDashboardOpen, setMetricsDashboardOpen] = useState(false);
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(
    null,
  );
  const [coWebsite, setCoWebsite] = useState<CoWebsiteEvent | null>(null);
  const [popup, setPopup] = useState<PopupEvent | null>(null);
  const [playerPosition, setPlayerPosition] = useState<{ x: number; y: number } | null>(null);
  const [deskInfo, setDeskInfo] = useState<{ assignedAgentId: string; title: string } | null>(null);
  const [bubbleLocked, setBubbleLocked] = useState(false);
  const [megaphoneActive, setMegaphoneActive] = useState(false);
  const [megaphoneSpeaker, setMegaphoneSpeaker] = useState<string | null>(null);
  const [currentRoom, setCurrentRoom] = useState('office');
  // Persisted via useLocalStorageState — hydration-safe. The hook returns the
  // default during SSR + first client render, then reads localStorage in a
  // post-mount effect, avoiding the `useState(() => localStorage.getItem(...))`
  // hydration mismatch.
  const [companionType, setCompanionType] = useLocalStorageState<CompanionType>(
    'selva:companion-type',
    '',
    {
      parse: (raw) => {
        const allowed: CompanionType[] = ['', 'cat', 'dog', 'robot', 'dragon', 'parrot'];
        return allowed.includes(raw as CompanionType) ? (raw as CompanionType) : '';
      },
    },
  );
  const [musicStatus, setMusicStatus] = useState('');
  const [mobileTab, setMobileTab] = useState('office');
  const [followingPlayer, setFollowingPlayer] = useState<string | null>(null);
  const [explorerMode, setExplorerMode] = useState(false);
  const [spotlightViewDismissed, setSpotlightViewDismissed] = useState(false);
  const [viewMode, setViewMode] = useLocalStorageState<'game' | 'simple'>(
    'selva:view-mode',
    'game',
    {
      parse: (raw) => (raw === 'simple' ? 'simple' : 'game'),
    },
  );

  const handleToggleViewMode = useCallback(() => {
    setViewMode((prev) => (prev === 'game' ? 'simple' : 'game'));
  }, [setViewMode]);

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
    async (requestId: string, feedback?: string): Promise<boolean> => {
      const ok = await approve(requestId, feedback || undefined);
      if (ok) setActiveApproval(null);
      return ok;
    },
    [approve],
  );

  const handleDeny = useCallback(
    async (requestId: string, feedback?: string): Promise<boolean> => {
      const ok = await deny(requestId, feedback || undefined);
      if (ok) setActiveApproval(null);
      return ok;
    },
    [deny],
  );

  const handlePlayerMove = useCallback(
    (x: number, y: number) => {
      sendMove(x, y);
      setPlayerPosition({ x, y });
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

  const handleDispatchOpen = useCallback(() => {
    setDashboardOpen(false);
    setApprovalPanelOpen(false);
    setDispatchPanelOpen(true);
  }, []);

  const handleApprovalPanelOpen = useCallback(() => {
    setDashboardOpen(false);
    setDispatchPanelOpen(false);
    setApprovalPanelOpen(true);
  }, []);

  const handleBlueprintOpen = useCallback(() => {
    if (isDemo) return; // No workflow editor in demo
    setWorkflowEditorOpen(true);
    setDashboardOpen(false);
    setDispatchPanelOpen(false);
    setApprovalPanelOpen(false);
  }, [isDemo]);

  const handleGenerateNotes = useCallback(() => {
    if (lastRecordingUrl) {
      void dispatchMeetingNotes(lastRecordingUrl);
      setMeetingNotesPanelOpen(true);
    }
  }, [lastRecordingUrl, dispatchMeetingNotes]);

  const handleMarketplaceOpen = useCallback(() => {
    if (isDemo) return; // No marketplace in demo
    setMarketplaceOpen(true);
    setDashboardOpen(false);
    setDispatchPanelOpen(false);
    setApprovalPanelOpen(false);
  }, [isDemo]);

  const handleCampaignDashboardOpen = useCallback(() => {
    if (isDemo) return;
    setCampaignDashboardOpen(true);
    setDashboardOpen(false);
    setDispatchPanelOpen(false);
    setApprovalPanelOpen(false);
  }, [isDemo]);

  const handleMapEditorOpen = useCallback(() => {
    if (isDemo) return; // No map editor in demo
    setMapEditorOpen(true);
    setDashboardOpen(false);
    setDispatchPanelOpen(false);
    setApprovalPanelOpen(false);
  }, [isDemo]);

  const handleDispatchClose = useCallback(() => {
    setDispatchPanelOpen(false);
  }, []);

  const handleMobileTabChange = useCallback((tab: string) => {
    setMobileTab(tab);
    if (tab === 'chat') {
      // Ensure chat panel is visible when switching to chat tab
      setDashboardOpen(false);
      setDispatchPanelOpen(false);
      setApprovalPanelOpen(false);
    } else if (tab === 'tasks') {
      setDashboardOpen(true);
      setDispatchPanelOpen(false);
      setApprovalPanelOpen(false);
    } else if (tab === 'office') {
      setDashboardOpen(false);
    } else if (tab === 'settings') {
      setAvatarEditorOpen(true);
    }
  }, []);

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

  // Reset spotlight dismissed state when spotlight becomes inactive
  useEffect(() => {
    if (!spotlightActive) {
      setSpotlightViewDismissed(false);
    }
  }, [spotlightActive]);

  // Send companion type to server when connected
  useEffect(() => {
    if (colyseusConnected && companionType) {
      sendCompanion(companionType);
    }
  }, [colyseusConnected, companionType, sendCompanion]);

  // Consolidated PhaserGame loader: one dynamic import wires up the event bus
  // ref (for emit-side bridges) and ALL gameEventBus listeners. This replaces
  // 5 separate `import('@/game/PhaserGame').then(...)` calls that each
  // raced against component cleanup independently. The handler bodies only
  // call setState for component-local UI state and never close over hook
  // outputs that change frequently, so binding once on mount is safe — when
  // the slices they update change, React re-renders without rebinding.
  useEffect(() => {
    let mounted = true;
    const cleanups: Array<() => void> = [];
    import('@/game/PhaserGame').then((mod) => {
      if (!mounted) return;
      gameEventBusRef.current = mod.gameEventBus;
      cleanups.push(
        mod.gameEventBus.on('open_desk_info', (detail: unknown) => {
          const event = detail as { title: string; assignedAgentId: string };
          setDeskInfo({ assignedAgentId: event.assignedAgentId, title: event.title });
        }),
        mod.gameEventBus.on('open_whiteboard', () => {
          setWhiteboardOpen(true);
          setDashboardOpen(false);
          setDispatchPanelOpen(false);
          setApprovalPanelOpen(false);
        }),
        mod.gameEventBus.on('follow-status', (detail: unknown) => {
          const { following, name } = detail as { following: boolean; name: string };
          setFollowingPlayer(following ? name : null);
        }),
        mod.gameEventBus.on('explorer-mode', (detail: unknown) => {
          setExplorerMode(detail as boolean);
        }),
        mod.gameEventBus.on('room_transition', (detail: unknown) => {
          const { roomId } = detail as { roomId: string };
          setCurrentRoom(roomId);
          const url = new URL(window.location.href);
          url.searchParams.set('map', roomId);
          window.history.replaceState({}, '', url.toString());
        }),
      );
    });
    return () => {
      mounted = false;
      cleanups.forEach((c) => c());
    };
  }, []);

  return (
    <ErrorBoundary>
    <ToastProvider>
    <main className="relative h-screen w-screen overflow-hidden bg-slate-900 scanline-overlay">
      {isDemo && <DemoBanner />}

      {viewMode === 'game' ? (
        <>
          <PhaserGame
            onApprovalOpen={handleApprovalOpen}
            officeState={officeState}
            sessionId={sessionId}
            onPlayerMove={handlePlayerMove}
            onEmote={handleEmote}
            onCoWebsite={handleCoWebsite}
            onPopup={handlePopup}
            onDispatchOpen={handleDispatchOpen}
            onBlueprintOpen={handleBlueprintOpen}
          />

          <HUD
            activeAgentCount={officeState?.activeAgentCount ?? 0}
            pendingApprovalCount={pendingApprovals.length}
            computeTokens={computeTokens}
            colyseusConnected={colyseusConnected}
            approvalsConnected={approvalsConnected}
            departments={officeState?.departments ?? []}
            playerPosition={playerPosition}
            userName={sessionUser?.name ?? sessionUser?.email ?? null}
            onApprovalClick={handleApprovalPanelOpen}
            followingPlayer={followingPlayer}
            explorerMode={explorerMode}
            viewMode={viewMode}
            onToggleViewMode={handleToggleViewMode}
          />

          {/* Ops controls (left side, below HUD) — hidden in demo */}
          {!isDemo && (
            <div className="absolute top-20 sm:top-24 left-2 sm:left-4 z-hud flex gap-1">
              <button
                onClick={() => {
                  setOpsFeedOpen((prev) => {
                    const next = !prev;
                    if (next && typeof window !== 'undefined' && window.innerWidth < 768) {
                      setChatForceCollapsed(true);
                    }
                    return next;
                  });
                  setDashboardOpen(false);
                }}
                className={`rounded px-3 py-2 font-mono text-xs min-h-[44px] md:px-2 md:py-1 md:text-[8px] md:min-h-0 retro-btn ${
                  opsFeedOpen ? 'bg-emerald-600 text-white' : 'bg-slate-800/90 text-slate-300 hover:bg-slate-700'
                }`}
                aria-label="Toggle ops feed"
              >
                Ops Feed
              </button>
              <button
                onClick={() => { setMetricsDashboardOpen(true); }}
                className="rounded bg-slate-800/90 px-3 py-2 font-mono text-xs min-h-[44px] md:px-2 md:py-1 md:text-[8px] md:min-h-0 text-slate-300 retro-btn hover:bg-slate-700"
                aria-label="Open metrics dashboard"
              >
                Metrics
              </button>
              <button
                onClick={handleCampaignDashboardOpen}
                className="rounded bg-rose-900/90 px-3 py-2 font-mono text-xs min-h-[44px] md:px-2 md:py-1 md:text-[8px] md:min-h-0 text-rose-200 retro-btn hover:bg-rose-800"
                aria-label="Open campaign dashboard"
              >
                Campaigns
              </button>
            </div>
          )}

          {!isDemo && (
            <OpsFeed
              open={opsFeedOpen}
              onClose={() => { setOpsFeedOpen(false); setChatForceCollapsed(false); }}
            />
          )}

          <DashboardPanel
            open={dashboardOpen}
            onToggle={() => setDashboardOpen((prev) => { if (!prev) setApprovalPanelOpen(false); return !prev; })}
            departments={officeState?.departments ?? []}
            onNewTask={handleDispatchOpen}
            onOpenMarketplace={isDemo ? undefined : handleMarketplaceOpen}
            onOpenCampaigns={isDemo ? undefined : handleCampaignDashboardOpen}
            onOpenMapEditor={isDemo ? undefined : handleMapEditorOpen}
          />

          <ApprovalPanel
            open={approvalPanelOpen}
            onClose={() => setApprovalPanelOpen(false)}
            pendingApprovals={pendingApprovals}
            onApprove={handleApprove}
            onDeny={handleDeny}
            connected={approvalsConnected}
          />

          <ChatPanel
            messages={officeState?.chatMessages ?? []}
            onSend={sendChat}
            localSessionId={sessionId ?? ''}
            forceCollapsed={chatForceCollapsed}
            onExpand={() => {
              setChatForceCollapsed(false);
              if (typeof window !== 'undefined' && window.innerWidth < 768) {
                setOpsFeedOpen(false);
              }
            }}
          />

          <VideoOverlay peers={peers} localStream={localStream} screenSharing={screenSharing} />
          <MediaControls
            audioEnabled={audioEnabled}
            videoEnabled={videoEnabled}
            onToggleAudio={toggleAudio}
            onToggleVideo={toggleVideo}
            screenSharing={screenSharing}
            onToggleScreenShare={toggleScreenShare}
            screenShareQuality={screenShareQuality}
            onScreenShareQualityChange={setScreenShareQuality}
            bubbleLocked={bubbleLocked}
            noiseSuppression={noiseSuppression}
            onToggleNoiseSuppression={toggleNoiseSuppression}
            onToggleLockBubble={() => {
              if (bubbleLocked) {
                sendUnlockBubble();
                setBubbleLocked(false);
              } else {
                sendLockBubble();
                setBubbleLocked(true);
              }
            }}
            visible={peers.length > 0 || !!localStream}
          />
          <RecordingControls
            recordingState={recordingState}
            formattedDuration={formattedDuration}
            onStart={startRecording}
            onStop={stopRecording}
            visible={peers.length > 0 || !!localStream}
            lastRecordingUrl={lastRecordingUrl}
            onGenerateNotes={handleGenerateNotes}
          />
          <MegaphoneControls
            active={megaphoneActive}
            speakerName={megaphoneSpeaker}
            isLocalSpeaker={megaphoneActive && megaphoneSpeaker === (sessionUser?.name ?? sessionUser?.email ?? null)}
            onStart={() => { sendMegaphoneStart(); setMegaphoneActive(true); setMegaphoneSpeaker(sessionUser?.name ?? sessionUser?.email ?? 'You'); }}
            onStop={() => { sendMegaphoneStop(); setMegaphoneActive(false); setMegaphoneSpeaker(null); }}
            visible={peers.length > 0 || !!localStream}
          />
          <SpotlightControls
            active={spotlightActive}
            presenterName={spotlightPresenterName}
            isPresenting={spotlightIsPresenting}
            onStart={startSpotlight}
            onStop={stopSpotlight}
            visible={peers.length > 0 || !!localStream}
          />
          {!spotlightViewDismissed && (
            <SpotlightView
              active={spotlightActive}
              isPresenting={spotlightIsPresenting}
              presenterName={spotlightPresenterName}
              presenterSessionId={spotlightPresenterSessionId}
              peers={peers}
              onClose={() => setSpotlightViewDismissed(true)}
            />
          )}
          <RoomNavigator
            currentRoom={currentRoom}
            onChangeRoom={(roomId) => setCurrentRoom(roomId)}
            visible={colyseusConnected}
          />

          <EmotePicker onEmote={handleEmote} />

          <AvatarEditor
            open={avatarEditorOpen}
            initialConfig={avatarConfig}
            onSave={handleAvatarSave}
            onClose={() => setAvatarEditorOpen(false)}
            companionType={companionType}
            onCompanionChange={(type) => {
              // Setter writes to both React state and localStorage atomically.
              setCompanionType(type as CompanionType);
              sendCompanion(type);
            }}
          />

          <button
            onClick={() => setAvatarEditorOpen(true)}
            className="absolute top-4 right-4 z-hud hidden sm:block rounded bg-slate-800/90 px-3 py-1 text-xs text-slate-300 retro-btn hover:bg-slate-700"
            aria-label="Open avatar editor"
          >
            Avatar
          </button>

          {/* Right-side controls — hide calendar in demo, hide most on mobile */}
          <div className="absolute top-14 right-2 sm:right-4 z-hud hidden sm:flex flex-col gap-1">
            {!isDemo && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    setCalendarPanelOpen((prev) => !prev);
                    setDashboardOpen(false);
                    setDispatchPanelOpen(false);
                    setApprovalPanelOpen(false);
                  }}
                  className={`rounded bg-slate-800/90 px-3 py-1 text-xs retro-btn ${
                    calendarConnected
                      ? calendarBusy
                        ? 'text-amber-400 hover:bg-amber-900/40'
                        : 'text-emerald-400 hover:bg-emerald-900/40'
                      : 'text-slate-300 hover:bg-slate-700'
                  }`}
                  aria-label="Toggle calendar panel"
                >
                  Calendar{calendarBusy ? ' (busy)' : ''}
                </button>
              </div>
            )}
            <StatusSelector
              currentStatus={playerStatus}
              onStatusChange={changePlayerStatus}
            />
            <MusicStatus
              currentStatus={musicStatus}
              onStatusChange={(status) => {
                setMusicStatus(status);
                sendMusicStatus(status);
              }}
            />
          </div>

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

          <DeskInfoPanel
            open={!!deskInfo}
            onClose={() => setDeskInfo(null)}
            assignedAgentId={deskInfo?.assignedAgentId ?? ''}
            deskTitle={deskInfo?.title ?? 'Desk'}
            departments={officeState?.departments ?? []}
          />
        </>
      ) : (
        <SimplifiedView
          departments={officeState?.departments ?? []}
          pendingApprovals={pendingApprovals}
          chatMessages={officeState?.chatMessages ?? []}
          onSendChat={sendChat}
          onApprove={handleApprove}
          onDeny={handleDeny}
          onDispatchTask={handleDispatchOpen}
          onOpenMarketplace={isDemo ? undefined : handleMarketplaceOpen}
          onToggleViewMode={handleToggleViewMode}
          colyseusConnected={colyseusConnected}
          approvalsConnected={approvalsConnected}
        />
      )}

      {/* Shared modals — available in both game and simplified view */}
      <TaskDispatchPanel
        open={dispatchPanelOpen}
        onClose={handleDispatchClose}
        onDispatch={dispatchTask}
        status={dispatchStatus}
        error={dispatchError}
        lastDispatchedTask={lastDispatchedTask}
        departments={officeState?.departments ?? []}
        onReset={resetDispatch}
      />

      {!isDemo && (
        <WorkflowEditor
          open={workflowEditorOpen}
          onClose={() => setWorkflowEditorOpen(false)}
          officeState={officeState}
        />
      )}

      <MeetingNotesPanel
        open={meetingNotesPanelOpen}
        onClose={() => { setMeetingNotesPanelOpen(false); resetMeetingNotes(); }}
        status={meetingNotesStatus}
        notes={meetingNotes}
        error={meetingNotesError}
      />

      {!isDemo && (
        <SkillMarketplace
          open={marketplaceOpen}
          onClose={() => setMarketplaceOpen(false)}
        />
      )}

      {!isDemo && (
        <CampaignDashboard
          open={campaignDashboardOpen}
          onClose={() => setCampaignDashboardOpen(false)}
        />
      )}

      {!isDemo && (
        <CalendarPanel
          open={calendarPanelOpen}
          onClose={() => setCalendarPanelOpen(false)}
          events={calendarEvents}
          isBusy={calendarBusy}
          connected={calendarConnected}
          status={calendarStatus}
          error={calendarError}
          onConnect={connectCalendar}
          onDisconnect={disconnectCalendar}
          onRefresh={refreshCalendar}
        />
      )}

      <WhiteboardPanel
        open={whiteboardOpen}
        onClose={() => setWhiteboardOpen(false)}
        strokes={whiteboardStrokes}
        tool={whiteboardTool}
        color={whiteboardColor}
        width={whiteboardWidth}
        colors={whiteboardColors}
        widths={whiteboardWidths}
        onSendStroke={whiteboardSendStroke}
        onClear={whiteboardClear}
        onToolChange={whiteboardSetTool}
        onColorChange={whiteboardSetColor}
        onWidthChange={whiteboardSetWidth}
      />

      {!isDemo && (
        <MapEditor
          open={mapEditorOpen}
          onClose={() => setMapEditorOpen(false)}
        />
      )}

      {!isDemo && (
        <MetricsDashboard
          open={metricsDashboardOpen}
          onClose={() => setMetricsDashboardOpen(false)}
        />
      )}

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

      {/* MADFAM Ecosystem Atrium — floating-window overlay. Hidden in
          demo mode (the office is sandboxed there) but always present
          in live mode. Office canvas remains interactive between
          windows because the overlay container is pointer-events:none. */}
      {!isDemo && <AtriumOverlay />}

      <MobileNav activeTab={mobileTab} onTabChange={handleMobileTabChange} />
    </main>
    </ToastProvider>
    </ErrorBoundary>
  );
}
