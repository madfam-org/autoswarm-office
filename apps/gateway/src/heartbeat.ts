import { CronJob } from "cron";
import { Octokit } from "@octokit/rest";
import WebSocket from "ws";

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

  constructor(
    nexusApiUrl: string,
    cronExpression: string = "*/30 * * * *"
  ) {
    this.nexusApiUrl = nexusApiUrl;
    this.cronExpression = cronExpression;
  }

  start(): void {
    this.cronJob = new CronJob(this.cronExpression, () => {
      this.tick().catch((err) => {
        console.error("[heartbeat] Error during tick:", err);
      });
    });
    this.cronJob.start();
    console.log("[heartbeat] CronJob started");
  }

  stop(): void {
    if (this.cronJob) {
      this.cronJob.stop();
      this.cronJob = null;
      console.log("[heartbeat] CronJob stopped");
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
      console.log("[heartbeat] WebSocket closed");
    }
  }

  async tick(): Promise<void> {
    const timestamp = new Date().toISOString();
    console.log(`[heartbeat] Tick at ${timestamp}`);

    const crmEvents = await this.scrapeCRM();
    const githubEvents = await this.scrapeGitHub();
    const ticketEvents = await this.scrapeTickets();

    const allEvents = [...crmEvents, ...githubEvents, ...ticketEvents];

    const waves = this.compileEnemyWaves(allEvents);

    if (waves.length > 0) {
      await this.dispatch(waves);
    } else {
      console.log("[heartbeat] No events to dispatch this cycle");
    }
  }

  private async scrapeCRM(): Promise<ExternalEvent[]> {
    try {
      console.log("[heartbeat] Scraping CRM for pending contacts and follow-ups...");
      // Stub: integrate with actual CRM API (HubSpot, Salesforce, etc.)
      return [];
    } catch (err) {
      console.error("[heartbeat] CRM scrape failed:", err);
      return [];
    }
  }

  private async scrapeGitHub(): Promise<ExternalEvent[]> {
    const token = process.env.GITHUB_TOKEN;
    const reposEnv = process.env.GITHUB_REPOS;
    if (!token || !reposEnv) {
      console.log("[heartbeat] GITHUB_TOKEN or GITHUB_REPOS not set; skipping GitHub scrape");
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

        console.log(
          `[heartbeat] GitHub: ${events.length} events from ${repo}`
        );
      } catch (err) {
        console.error(`[heartbeat] GitHub scrape failed for ${repo}:`, err);
      }
    }

    return events;
  }

  private async scrapeTickets(): Promise<ExternalEvent[]> {
    try {
      console.log("[heartbeat] Scraping support tickets for escalations and SLA breaches...");
      // Stub: integrate with ticketing system (Zendesk, Freshdesk, etc.)
      return [];
    } catch (err) {
      console.error("[heartbeat] Ticket scrape failed:", err);
      return [];
    }
  }

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

  private async dispatch(waves: EnemyWaveEvent[]): Promise<void> {
    try {
      const ws = this.getOrCreateWebSocket();

      await this.waitForOpen(ws);

      for (const wave of waves) {
        const message = JSON.stringify({
          type: "gateway:wave",
          data: wave,
        });
        ws.send(message);
        console.log(
          `[heartbeat] Dispatched ${wave.kind} from ${wave.source} (${wave.events.length} events)`
        );
      }
    } catch (err) {
      console.error("[heartbeat] Failed to dispatch waves:", err);
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
      console.log("[heartbeat] WebSocket connected to nexus-api");
    });

    this.ws.on("error", (err) => {
      console.error("[heartbeat] WebSocket error:", err);
    });

    this.ws.on("close", (code, reason) => {
      console.log(
        `[heartbeat] WebSocket closed (code=${code}, reason=${reason.toString()})`
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
