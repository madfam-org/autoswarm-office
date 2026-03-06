import { CronJob } from "cron";
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
    try {
      console.log("[heartbeat] Scraping GitHub for PRs, issues, and CI status...");
      // Stub: integrate with GitHub API via Octokit
      return [];
    } catch (err) {
      console.error("[heartbeat] GitHub scrape failed:", err);
      return [];
    }
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
