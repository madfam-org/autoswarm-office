import { CronJob } from "cron";
import { Octokit } from "@octokit/rest";
import WebSocket from "ws";
import type pino from "pino";
import { CRMScraper } from "./crm-scraper";

interface ExternalEvent {
  source: string;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

interface EnemyWaveEvent {
  kind: "enemy_wave" | "alert" | "report";
  source: string;
  events: ExternalEvent[];
  compiledAt: string;
}

export class HeartbeatService {
  private readonly nexusApiUrl: string;
  private readonly cronExpression: string;
  private cronJob: CronJob | null = null;
  private ws: WebSocket | null = null;
  private readonly crmScraper: CRMScraper | null;
  private readonly logger: pino.Logger;

  private _lastTickTime: string | null = null;
  private _totalTicks: number = 0;
  private _tickRunning = false;

  /** Dedup: recently dispatched lead/activity IDs → timestamp. 24h TTL. */
  private readonly recentlyDispatched = new Map<string, number>();
  private static readonly DEDUP_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
  private static readonly MAX_DISPATCHES_PER_TICK = 10;

  constructor(
    nexusApiUrl: string,
    cronExpression: string = "*/30 * * * *",
    logger: pino.Logger
  ) {
    this.nexusApiUrl = nexusApiUrl;
    this.cronExpression = cronExpression;
    this.logger = logger;

    const phyneCrmUrl = process.env.PHYNE_CRM_URL;
    const phyneCrmToken = process.env.PHYNE_CRM_TOKEN ?? "";
    const crmLogger = logger.child({ component: "crm-scraper" });
    this.crmScraper = phyneCrmUrl
      ? new CRMScraper(phyneCrmUrl, phyneCrmToken, crmLogger)
      : null;
  }

  /** ISO timestamp of the last completed tick, or null if no tick has run. */
  get lastTickTime(): string | null {
    return this._lastTickTime;
  }

  /** ISO timestamp of the next scheduled tick, or null if not running. */
  get nextTickTime(): string | null {
    if (!this.cronJob) return null;
    try {
      const next = this.cronJob.nextDate();
      return next.toISO();
    } catch {
      return null;
    }
  }

  /** Total number of ticks executed since the service started. */
  get totalTicks(): number {
    return this._totalTicks;
  }

  start(): void {
    this.cronJob = new CronJob(this.cronExpression, () => {
      this.tick().catch((err) => {
        this.logger.error({ err }, "Error during tick");
      });
    });
    this.cronJob.start();
    this.logger.info("CronJob started");
  }

  stop(): void {
    if (this.cronJob) {
      this.cronJob.stop();
      this.cronJob = null;
      this.logger.info("CronJob stopped");
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
      this.logger.info("WebSocket closed");
    }
  }

  async tick(): Promise<void> {
    // Concurrency guard — prevent overlapping ticks
    if (this._tickRunning) {
      this.logger.warn("Tick already running — skipping this invocation");
      return;
    }
    this._tickRunning = true;

    try {
      const timestamp = new Date().toISOString();
      this.logger.info({ timestamp }, "Tick started");

      const crmEvents = await this.scrapeCRM();
      const githubEvents = await this.scrapeGitHub();
      // Reuse CRM events for tickets instead of double-scraping
      const ticketEvents = crmEvents.filter((e) => e.type === "activity_overdue");
      const dedupedCRM = crmEvents.filter((e) => e.type !== "activity_overdue");

      const allEvents = [...dedupedCRM, ...githubEvents, ...ticketEvents];

      const waves = this.compileEnemyWaves(allEvents);

      if (waves.length > 0) {
        await this.dispatch(waves);
      } else {
        this.logger.info("No events to dispatch this cycle");
      }

      this._lastTickTime = timestamp;
      this._totalTicks += 1;
    } finally {
      this._tickRunning = false;
    }
  }

  private async scrapeCRM(): Promise<ExternalEvent[]> {
    if (!this.crmScraper) {
      this.logger.info("PHYNE_CRM_URL not set; skipping CRM scrape");
      return [];
    }

    try {
      this.logger.info("Scraping CRM via Phynd-CRM...");
      return await this.crmScraper.scrape();
    } catch (err) {
      this.logger.error({ err }, "CRM scrape failed");
      return [];
    }
  }

  private async scrapeGitHub(): Promise<ExternalEvent[]> {
    const token = process.env.GITHUB_TOKEN;
    const reposEnv = process.env.GITHUB_REPOS;
    if (!token || !reposEnv) {
      this.logger.info("GITHUB_TOKEN or GITHUB_REPOS not set; skipping GitHub scrape");
      return [];
    }

    const repos = reposEnv.split(",").map((r) => r.trim()).filter(Boolean);
    const octokit = new Octokit({ auth: token });
    const events: ExternalEvent[] = [];
    const now = new Date().toISOString();

    for (const repo of repos) {
      const [owner, name] = repo.split("/");
      if (!owner || !name) continue;

      try {
        // Fetch open PRs with review requests (max 10)
        const { data: prs } = await octokit.pulls.list({
          owner,
          repo: name,
          state: "open",
          per_page: 10,
        });

        for (const pr of prs) {
          if (pr.requested_reviewers && pr.requested_reviewers.length > 0) {
            events.push({
              source: "github",
              type: "pr_review_requested",
              payload: {
                repo,
                pr_number: pr.number,
                title: pr.title,
                author: pr.user?.login ?? "unknown",
                reviewers: pr.requested_reviewers.map((r) => r.login),
                url: pr.html_url,
              },
              timestamp: now,
            });
          }

          // Check CI status on head commit
          try {
            const { data: status } = await octokit.repos.getCombinedStatusForRef({
              owner,
              repo: name,
              ref: pr.head.sha,
            });

            if (status.state === "failure") {
              events.push({
                source: "github",
                type: "ci_failure",
                payload: {
                  repo,
                  pr_number: pr.number,
                  title: pr.title,
                  sha: pr.head.sha,
                  url: pr.html_url,
                },
                timestamp: now,
              });
            }
          } catch {
            // CI status may not be available for all commits
          }
        }

        // Fetch issues labeled 'critical' (max 5)
        const { data: issues } = await octokit.issues.listForRepo({
          owner,
          repo: name,
          labels: "critical",
          state: "open",
          per_page: 5,
        });

        for (const issue of issues) {
          if (issue.pull_request) continue; // skip PRs in issues endpoint
          events.push({
            source: "github",
            type: "escalation",
            payload: {
              repo,
              issue_number: issue.number,
              title: issue.title,
              url: issue.html_url,
              labels: issue.labels
                .map((l) => (typeof l === "string" ? l : l.name))
                .filter(Boolean),
            },
            timestamp: now,
          });
        }

        this.logger.info(
          { eventCount: events.length, repo },
          "GitHub scrape completed for repo"
        );
      } catch (err) {
        this.logger.error({ err, repo }, "GitHub scrape failed for repo");
      }
    }

    return events;
  }

  // scrapeTickets() removed — ticket events are now extracted from the
  // single scrapeCRM() call in tick() to avoid double-scraping PhyndCRM.

  private compileEnemyWaves(events: ExternalEvent[]): EnemyWaveEvent[] {
    if (events.length === 0) {
      return [];
    }

    const now = new Date().toISOString();
    const bySource = new Map<string, ExternalEvent[]>();

    for (const event of events) {
      const existing = bySource.get(event.source) ?? [];
      existing.push(event);
      bySource.set(event.source, existing);
    }

    const waves: EnemyWaveEvent[] = [];

    for (const [source, sourceEvents] of bySource) {
      const hasUrgent = sourceEvents.some(
        (e) => e.type === "escalation" || e.type === "sla_breach"
      );

      waves.push({
        kind: hasUrgent ? "alert" : "enemy_wave",
        source,
        events: sourceEvents,
        compiledAt: now,
      });
    }

    return waves;
  }

  // Auto-dispatch rules: map event types to SwarmTask graph types + skills
  private static readonly AUTO_DISPATCH_RULES: Record<
    string,
    { graphType: string; skills: string[]; hitl: boolean }
  > = {
    "github:pr_opened": { graphType: "review", skills: ["code-review"], hitl: false },
    "github:ci_failed": { graphType: "coding", skills: ["coding", "webapp-testing"], hitl: true },
    "github:issue_opened": { graphType: "research", skills: ["research"], hitl: false },
    "crm:hot_lead": { graphType: "crm", skills: ["crm-outreach"], hitl: false },
    "crm:high_intent_lead": { graphType: "crm", skills: ["crm-outreach"], hitl: false },
    "crm:lead_followup": { graphType: "crm", skills: ["crm-outreach"], hitl: false },
    "crm:activity_overdue": { graphType: "support", skills: ["customer-support"], hitl: false },
    "crm:support_ticket": { graphType: "support", skills: ["customer-support"], hitl: false },
    "crm:campaign_due": { graphType: "research", skills: ["research", "doc-coauthoring"], hitl: false },
  };

  private async dispatch(waves: EnemyWaveEvent[]): Promise<void> {
    // 1. Send waves to WebSocket (existing behavior for UI)
    try {
      const ws = this.getOrCreateWebSocket();
      await this.waitForOpen(ws);
      for (const wave of waves) {
        ws.send(JSON.stringify({ type: "gateway:wave", data: wave }));
        this.logger.info(
          { kind: wave.kind, source: wave.source, eventCount: wave.events.length },
          "Dispatched wave to WebSocket"
        );
      }
    } catch (err) {
      this.logger.error({ err }, "Failed to dispatch waves to WebSocket");
    }

    // 2. Auto-dispatch matching events as SwarmTasks (new behavior)
    if (process.env.AUTO_DISPATCH_ENABLED !== "true") return;

    const dispatchUrl = process.env.NEXUS_API_URL ?? this.nexusApiUrl.replace("ws", "http");
    const token = process.env.WORKER_API_TOKEN;
    if (!token || token === "dev-bypass") {
      this.logger.error("AUTO_DISPATCH_ENABLED but WORKER_API_TOKEN not set or is dev-bypass — skipping dispatch");
      return;
    }

    // Purge stale dedup entries (older than 24h)
    const now = Date.now();
    for (const [k, t] of this.recentlyDispatched) {
      if (now - t > HeartbeatService.DEDUP_TTL_MS) this.recentlyDispatched.delete(k);
    }

    let dispatchCount = 0;

    for (const wave of waves) {
      if (dispatchCount >= HeartbeatService.MAX_DISPATCHES_PER_TICK) break;

      for (const event of wave.events) {
        if (dispatchCount >= HeartbeatService.MAX_DISPATCHES_PER_TICK) {
          this.logger.warn(
            { capped: true, max: HeartbeatService.MAX_DISPATCHES_PER_TICK },
            "Dispatch cap reached for this tick"
          );
          break;
        }

        const eventKey = `${event.source}:${event.type}`;
        const rule = HeartbeatService.AUTO_DISPATCH_RULES[eventKey];
        if (!rule) continue;

        // Dedup: skip if this lead/activity was already dispatched in the last 24h
        const dedupId = String(event.payload?.lead_id || event.payload?.activity_id || "");
        const dedupKey = `${eventKey}:${dedupId}`;
        if (dedupId && this.recentlyDispatched.has(dedupKey)) {
          this.logger.debug({ dedupKey }, "Skipping duplicate dispatch");
          continue;
        }

        // PII-safe description: use opaque IDs, not contact names
        const score = event.payload.score || "?";
        const description = `[auto] ${eventKey}: lead:${dedupId} (score: ${score})`;

        try {
          const resp = await fetch(`${dispatchUrl}/api/v1/swarms/dispatch`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              description,
              graph_type: rule.graphType,
              required_skills: rule.skills,
              payload: {
                auto_dispatched: true,
                trigger_event: eventKey,
                crm_action: "email",
                // Explicit field pick — no ...event.payload spread
                lead_id: event.payload?.lead_id,
                contact_id: event.payload?.contact_id,
                score: event.payload?.score,
                stage: event.payload?.stage,
                activity_id: event.payload?.activity_id,
                playbook: {
                  name: "Lead Response",
                  trigger_event: eventKey,
                  allowed_actions: ["api_call", "email_send", "crm_update", "marketing_send"],
                  token_budget: 50,
                  financial_cap_cents: 5000, // $50/day cap
                  require_approval: true,    // HITL required
                },
              },
            }),
          });

          if (resp.ok) {
            if (dedupId) this.recentlyDispatched.set(dedupKey, now);
            dispatchCount++;
            this.logger.info({ eventKey, graphType: rule.graphType, dispatchCount }, "Auto-dispatched SwarmTask");
          } else {
            this.logger.warn({ eventKey, status: resp.status }, "Auto-dispatch failed");
          }
        } catch (err) {
          this.logger.error({ err, eventKey }, "Auto-dispatch error");
        }
      }
    }
  }

  private getOrCreateWebSocket(): WebSocket {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return this.ws;
    }

    if (this.ws) {
      this.ws.removeAllListeners();
      this.ws.close();
    }

    this.ws = new WebSocket(this.nexusApiUrl);

    this.ws.on("open", () => {
      this.logger.info("WebSocket connected to nexus-api");
    });

    this.ws.on("error", (err) => {
      this.logger.error({ err }, "WebSocket error");
    });

    this.ws.on("close", (code, reason) => {
      this.logger.info(
        { code, reason: reason.toString() },
        "WebSocket closed"
      );
      this.ws = null;
    });

    return this.ws;
  }

  private waitForOpen(ws: WebSocket): Promise<void> {
    if (ws.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }

    return new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("WebSocket connection timeout (10s)"));
      }, 10_000);

      ws.once("open", () => {
        clearTimeout(timeout);
        resolve();
      });

      ws.once("error", (err) => {
        clearTimeout(timeout);
        reject(err);
      });
    });
  }
}
