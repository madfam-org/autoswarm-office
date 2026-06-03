'use client';

import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import { CloseButton } from '@selva/ui';
import type { TaskBoardItem } from '@selva/shared-types';

import { TulanaReadinessBadge } from '@/components/campaigns/TulanaReadinessBadge';
import type {
  SocialPlatform,
  TulanaSkuCampaignPack,
} from '@/components/campaigns/types';
import { gameEventBus } from '@/game/PhaserGame';
import { useCampaigns, parseTulanaImportJson } from '@/hooks/useCampaigns';
import { useScheduledActions } from '@/hooks/useScheduledActions';
import { useTaskBoard } from '@/hooks/useTaskBoard';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useToast } from '@/hooks/useToast';
import { EVENT_CHAT_FOCUS } from '@/lib/constants';

interface CampaignDashboardProps {
  open: boolean;
  onClose: () => void;
}

type TabId = 'import' | 'tasks' | 'scheduled' | 'actions';

const TABS: { id: TabId; label: string }[] = [
  { id: 'import', label: 'Import' },
  { id: 'tasks', label: 'Campaign Tasks' },
  { id: 'scheduled', label: 'Scheduled Posts' },
  { id: 'actions', label: 'Handoff & Feedback' },
];

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function campaignTasksFromBoard(board: ReturnType<typeof useTaskBoard>['board']): TaskBoardItem[] {
  if (!board) return [];
  const items: TaskBoardItem[] = [];
  for (const column of Object.values(board.columns)) {
    for (const task of column) {
      if (task.labels?.includes('campaign')) items.push(task);
    }
  }
  return items.sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
}

export const CampaignDashboard: FC<CampaignDashboardProps> = ({ open, onClose }) => {
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const { addToast } = useToast();
  const [tab, setTab] = useState<TabId>('import');
  const [importJson, setImportJson] = useState('');
  const [allowBlocked, setAllowBlocked] = useState(false);
  const [dispatchTasks, setDispatchTasks] = useState(true);
  const [selectedPack, setSelectedPack] = useState<TulanaSkuCampaignPack | null>(null);
  const [draftVariants, setDraftVariants] = useState('');
  const [socialPlatform, setSocialPlatform] = useState<SocialPlatform>('reddit');
  const [redditSubreddit, setRedditSubreddit] = useState('selva');
  const [feedbackSummary, setFeedbackSummary] = useState('');

  const {
    status: campaignStatus,
    error: campaignError,
    lastImport,
    importPacks,
    submitHandoff,
    submitSchedule,
    submitFeedback,
    reset: resetCampaigns,
  } = useCampaigns();

  const { board, refresh: refreshBoard } = useTaskBoard();
  const { actions, loading: actionsLoading, approve, deny, refresh: refreshActions } =
    useScheduledActions();

  const campaignTasks = useMemo(() => campaignTasksFromBoard(board), [board]);
  const pendingHitl = useMemo(
    () => actions.filter((a) => a.hitl_status === 'pending' && a.status === 'pending'),
    [actions],
  );

  useEffect(() => {
    if (open) {
      gameEventBus.emit(EVENT_CHAT_FOCUS, true);
      return () => {
        gameEventBus.emit(EVENT_CHAT_FOCUS, false);
      };
    }
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) {
      setTab('import');
      setImportJson('');
      setSelectedPack(null);
      setDraftVariants('');
      setFeedbackSummary('');
      resetCampaigns();
    }
  }, [open, resetCampaigns]);

  useEffect(() => {
    if (lastImport?.accepted.length && !selectedPack) {
      setSelectedPack(lastImport.accepted[0] ?? null);
    }
  }, [lastImport, selectedPack]);

  const handleImport = useCallback(async () => {
    try {
      const packs = parseTulanaImportJson(importJson);
      const result = await importPacks(
        { packs, allow_blocked: allowBlocked, dispatch_tasks: dispatchTasks },
        `tulana-import-ui:${Date.now()}`,
      );
      if (result) {
        addToast(
          `Imported ${result.accepted.length} SKU(s); dispatched ${result.dispatched_task_ids.length}`,
          'success',
        );
        await refreshBoard();
        setTab('tasks');
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Invalid JSON', 'error');
    }
  }, [
    importJson,
    allowBlocked,
    dispatchTasks,
    importPacks,
    addToast,
    refreshBoard,
  ]);

  const handleHandoff = useCallback(async () => {
    if (!selectedPack) {
      addToast('Select a Tulana pack first', 'warning');
      return;
    }
    const variants = draftVariants
      .split('\n---\n')
      .map((v) => v.trim())
      .filter(Boolean);
    if (!variants.length) {
      addToast('Add at least one draft variant', 'warning');
      return;
    }
    const result = await submitHandoff(
      {
        sku_key: selectedPack.sku_key,
        audience: selectedPack.audience,
        draft_variants: variants,
        tulana_pack: selectedPack,
        campaign_name: `${selectedPack.sku_key} → ${selectedPack.audience}`,
      },
      `crm-handoff-ui:${selectedPack.sku_key}`,
    );
    if (result) {
      addToast('CRM handoff queued (HITL)', 'success');
      await refreshBoard();
    }
  }, [selectedPack, draftVariants, submitHandoff, addToast, refreshBoard]);

  const handleScheduleSocial = useCallback(async () => {
    if (!selectedPack) {
      addToast('Select a Tulana pack first', 'warning');
      return;
    }
    const bodyText =
      draftVariants.split('\n---\n').map((v) => v.trim()).filter(Boolean)[0] ??
      selectedPack.value_prop ??
      'Campaign copy pending review';
    const when = new Date(Date.now() + 60 * 60 * 1000);
    const payload: Record<string, unknown> =
      socialPlatform === 'reddit'
        ? {
            subreddit: redditSubreddit,
            title: `${selectedPack.sku_key} for ${selectedPack.audience}`,
            body: bodyText.slice(0, 4000),
          }
        : socialPlatform === 'bluesky'
          ? { text: bodyText.slice(0, 300) }
          : socialPlatform === 'mastodon'
            ? { instance: 'mastodon.social', status: bodyText.slice(0, 500) }
            : {
                recipient: 'campaign@example.com',
                subject: `${selectedPack.sku_key} campaign`,
                body: bodyText.slice(0, 4000),
              };

    const result = await submitSchedule(
      {
        sku_key: selectedPack.sku_key,
        platform: socialPlatform,
        require_hitl: true,
        posts: [{ scheduled_for: when.toISOString(), payload }],
      },
      `schedule-social-ui:${selectedPack.sku_key}`,
    );
    if (result) {
      addToast(`Scheduled ${result.count} post(s) with HITL`, 'success');
      await refreshActions();
      setTab('scheduled');
    }
  }, [
    selectedPack,
    draftVariants,
    socialPlatform,
    redditSubreddit,
    submitSchedule,
    addToast,
    refreshActions,
  ]);

  const handleFeedback = useCallback(async () => {
    if (!selectedPack || !feedbackSummary.trim()) {
      addToast('Pack + summary required for Tulana feedback', 'warning');
      return;
    }
    const result = await submitFeedback(
      {
        sku_key: selectedPack.sku_key,
        summary: feedbackSummary.trim(),
        outcomes: [{ metric: 'campaign_ui_signal', value: 1, source: 'selva_campaign_ui' }],
        campaign_name: `${selectedPack.sku_key} campaign`,
      },
      `tulana-feedback-ui:${selectedPack.sku_key}`,
    );
    if (result) {
      addToast(result.message || 'Feedback sent to Tulana', 'success');
    }
  }, [selectedPack, feedbackSummary, submitFeedback, addToast]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-modal animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label="Campaign dashboard"
    >
      <div className="absolute inset-0 bg-slate-900/95 backdrop-blur-sm" onClick={onClose} />

      <div
        ref={trapRef}
        className="absolute inset-4 sm:inset-6 lg:inset-8 retro-panel pixel-border-accent animate-pop-in flex flex-col overflow-hidden"
      >
        <div className="flex flex-col gap-3 border-b border-slate-700 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="pixel-text text-[11px] uppercase tracking-wider text-indigo-400">
              Campaign Dashboard
            </h2>
            <p className="font-mono text-[8px] text-slate-500 mt-1">
              Tulana packs · lanes · drafts · HITL social · CRM handoff
            </p>
          </div>
          <CloseButton onClick={onClose} label="Close campaigns" shortcut="ESC" />
        </div>

        <div className="flex gap-1 overflow-x-auto border-b border-slate-800 px-3 py-2">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`whitespace-nowrap px-2 py-1 font-mono text-[8px] uppercase transition-colors ${
                tab === t.id
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              {t.label}
              {t.id === 'scheduled' && pendingHitl.length > 0 ? ` (${pendingHitl.length})` : ''}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {campaignError && (
            <p className="mb-3 rounded border border-red-800 bg-red-950/40 px-3 py-2 font-mono text-[9px] text-red-300">
              {campaignError}
            </p>
          )}

          {tab === 'import' && (
            <div className="space-y-3 max-w-3xl">
              <p className="font-mono text-[9px] text-slate-400">
                Paste a Tulana SKU export (JSON array or {'{ "packs": [...] }'}). Accepted SKUs
                can auto-dispatch campaign planning tasks.
              </p>
              <textarea
                value={importJson}
                onChange={(e) => setImportJson(e.target.value)}
                rows={12}
                placeholder='[{ "sku_key": "...", "audience": "...", "ga_readiness": "near_ready", "last_verified_at": "2026-05-29T00:00:00Z" }]'
                className="w-full resize-y rounded border border-slate-700 bg-slate-800/80 px-3 py-2 font-mono text-[9px] text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
              />
              <div className="flex flex-wrap gap-4 font-mono text-[8px] text-slate-300">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={allowBlocked}
                    onChange={(e) => setAllowBlocked(e.target.checked)}
                  />
                  Allow blocked SKUs (waitlist lane)
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={dispatchTasks}
                    onChange={(e) => setDispatchTasks(e.target.checked)}
                  />
                  Dispatch planning tasks
                </label>
              </div>
              <button
                type="button"
                onClick={() => void handleImport()}
                disabled={campaignStatus === 'loading' || !importJson.trim()}
                className="rounded bg-indigo-600 px-4 py-2 font-mono text-[9px] text-white retro-btn hover:bg-indigo-500 disabled:opacity-50"
              >
                {campaignStatus === 'loading' ? 'Importing…' : 'Import Tulana Pack'}
              </button>

              {lastImport && (
                <div className="space-y-2 pt-2">
                  <h3 className="pixel-text text-[8px] uppercase text-slate-500">Last import</h3>
                  {lastImport.accepted.map((pack) => (
                    <div
                      key={pack.sku_key}
                      className="retro-panel flex items-center justify-between gap-2 p-2"
                    >
                      <span className="font-mono text-[9px] text-slate-200">{pack.sku_key}</span>
                      <TulanaReadinessBadge readiness={pack.ga_readiness} />
                    </div>
                  ))}
                  {lastImport.rejected.map((row) => (
                    <div
                      key={row.sku_key}
                      className="rounded border border-red-900/50 bg-red-950/20 p-2 font-mono text-[8px] text-red-300"
                    >
                      Rejected {row.sku_key}: {row.errors.join(', ')}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === 'tasks' && (
            <div className="space-y-2">
              {campaignTasks.length === 0 ? (
                <p className="font-mono text-[9px] text-slate-500 italic">
                  No campaign tasks yet — import a Tulana pack with dispatch enabled.
                </p>
              ) : (
                campaignTasks.map((task) => (
                  <div
                    key={task.id}
                    className="retro-panel p-3 border-l-2 border-indigo-500 animate-fade-in-up"
                  >
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <span className="pixel-text text-[8px] text-indigo-300">
                        {task.title ?? task.description.slice(0, 60)}
                      </span>
                      <span className="font-mono text-[7px] text-slate-500 uppercase">
                        {task.graph_type} · {task.status}
                      </span>
                    </div>
                    <p className="font-mono text-[8px] text-slate-400 line-clamp-2">
                      {task.description}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {task.labels.map((label) => (
                        <span
                          key={label}
                          className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[7px] text-slate-400 border border-slate-700"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {tab === 'scheduled' && (
            <div className="space-y-2">
              {actionsLoading && (
                <p className="font-mono text-[8px] text-slate-500">Loading scheduled actions…</p>
              )}
              {actions.length === 0 && !actionsLoading ? (
                <p className="font-mono text-[9px] text-slate-500 italic">
                  No scheduled social posts yet.
                </p>
              ) : (
                actions.map((action) => (
                  <div
                    key={action.id}
                    className="retro-panel p-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="font-mono text-[9px] text-slate-200">
                          {(action.payload.platform as string) ?? action.action_type}
                        </span>
                        <span className="font-mono text-[7px] text-slate-500">
                          {action.status}
                          {action.hitl_status ? ` · HITL ${action.hitl_status}` : ''}
                        </span>
                      </div>
                      <p className="font-mono text-[8px] text-slate-400">
                        {formatWhen(action.scheduled_for)}
                        {action.payload.sku_key ? ` · ${String(action.payload.sku_key)}` : ''}
                      </p>
                      {action.last_error && (
                        <p className="font-mono text-[7px] text-red-400 mt-1">{action.last_error}</p>
                      )}
                    </div>
                    {action.hitl_status === 'pending' && action.status === 'pending' && (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            void approve(action.id).then((ok) =>
                              ok
                                ? addToast('Post approved for dispatch', 'success')
                                : addToast('Approve failed', 'error'),
                            )
                          }
                          className="rounded bg-emerald-700 px-3 py-1 font-mono text-[8px] text-white retro-btn"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void deny(action.id).then((ok) =>
                              ok
                                ? addToast('Post denied', 'warning')
                                : addToast('Deny failed', 'error'),
                            )
                          }
                          className="rounded bg-red-800 px-3 py-1 font-mono text-[8px] text-white retro-btn"
                        >
                          Deny
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {tab === 'actions' && (
            <div className="grid gap-4 lg:grid-cols-2 max-w-5xl">
              <div className="space-y-3">
                <h3 className="pixel-text text-[8px] uppercase text-slate-500">Active SKU</h3>
                <select
                  value={selectedPack?.sku_key ?? ''}
                  onChange={(e) => {
                    const pack =
                      lastImport?.accepted.find((p) => p.sku_key === e.target.value) ?? null;
                    setSelectedPack(pack);
                  }}
                  className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 font-mono text-[9px] text-slate-200"
                >
                  <option value="">Select imported SKU…</option>
                  {(lastImport?.accepted ?? []).map((pack) => (
                    <option key={pack.sku_key} value={pack.sku_key}>
                      {pack.sku_key} ({pack.audience})
                    </option>
                  ))}
                </select>
                {selectedPack && (
                  <div className="retro-panel p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[9px] text-slate-200">
                        {selectedPack.sku_key}
                      </span>
                      <TulanaReadinessBadge readiness={selectedPack.ga_readiness} />
                    </div>
                    <p className="font-mono text-[8px] text-slate-400">{selectedPack.audience}</p>
                    {selectedPack.value_prop && (
                      <p className="font-mono text-[8px] text-slate-300">{selectedPack.value_prop}</p>
                    )}
                  </div>
                )}

                <label className="block">
                  <span className="pixel-text text-[8px] uppercase text-slate-500">
                    Draft variants (separate with ---)
                  </span>
                  <textarea
                    value={draftVariants}
                    onChange={(e) => setDraftVariants(e.target.value)}
                    rows={6}
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 font-mono text-[9px] text-slate-200"
                    placeholder="Variant A…&#10;---&#10;Variant B…"
                  />
                </label>
              </div>

              <div className="space-y-4">
                <div className="retro-panel p-3 space-y-2">
                  <h4 className="pixel-text text-[8px] uppercase text-emerald-400">CRM handoff</h4>
                  <p className="font-mono text-[8px] text-slate-500">
                    Queue Phynd CRM staging with HITL approval.
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleHandoff()}
                    disabled={campaignStatus === 'loading'}
                    className="rounded bg-emerald-700 px-3 py-1.5 font-mono text-[8px] text-white retro-btn disabled:opacity-50"
                  >
                    Submit CRM Handoff
                  </button>
                </div>

                <div className="retro-panel p-3 space-y-2">
                  <h4 className="pixel-text text-[8px] uppercase text-cyan-400">Schedule social</h4>
                  <div className="flex flex-wrap gap-2">
                    <select
                      value={socialPlatform}
                      onChange={(e) => setSocialPlatform(e.target.value as SocialPlatform)}
                      className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[8px] text-slate-200"
                    >
                      <option value="reddit">Reddit</option>
                      <option value="bluesky">Bluesky</option>
                      <option value="mastodon">Mastodon</option>
                      <option value="email">Email</option>
                    </select>
                    {socialPlatform === 'reddit' && (
                      <input
                        value={redditSubreddit}
                        onChange={(e) => setRedditSubreddit(e.target.value)}
                        placeholder="subreddit"
                        className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[8px] text-slate-200"
                      />
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleScheduleSocial()}
                    disabled={campaignStatus === 'loading'}
                    className="rounded bg-cyan-700 px-3 py-1.5 font-mono text-[8px] text-white retro-btn disabled:opacity-50"
                  >
                    Schedule Post (HITL)
                  </button>
                </div>

                <div className="retro-panel p-3 space-y-2">
                  <h4 className="pixel-text text-[8px] uppercase text-purple-400">Tulana feedback</h4>
                  <textarea
                    value={feedbackSummary}
                    onChange={(e) => setFeedbackSummary(e.target.value)}
                    rows={3}
                    placeholder="Campaign outcome summary for Tulana buyer signals…"
                    className="w-full rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 font-mono text-[9px] text-slate-200"
                  />
                  <button
                    type="button"
                    onClick={() => void handleFeedback()}
                    disabled={campaignStatus === 'loading'}
                    className="rounded bg-purple-700 px-3 py-1.5 font-mono text-[8px] text-white retro-btn disabled:opacity-50"
                  >
                    Push to Tulana
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
