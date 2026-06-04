import { describe, it, expect, vi, afterEach } from "vitest";
import { mockLogger } from "./helpers";

// We test the HeartbeatService methods by importing the class and mocking
// external dependencies (Octokit, WebSocket).

/**
 * Minimal structural types for the private surface we drive from tests.
 * The real fields live on HeartbeatService; this alias just lets us cast
 * without reaching for `any` every time. Keeping it loose — tests don't
 * need to model the full private API, only what they invoke or inject.
 */
interface ExternalEvent {
  source: string;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}
interface EnemyWave {
  kind: string;
  source: string;
  events: ExternalEvent[];
  compiledAt: string;
}
interface HeartbeatPrivates {
  scrapeGitHub(): Promise<ExternalEvent[]>;
  compileEnemyWaves(events: ExternalEvent[]): EnemyWave[];
  dispatch(waves: EnemyWave[]): Promise<void>;
  ws: unknown;
}

// ---------------------------------------------------------------------------
// scrapeGitHub
// ---------------------------------------------------------------------------

describe("scrapeGitHub", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.GITHUB_TOKEN;
    delete process.env.GITHUB_REPOS;
  });

  it("returns empty when GITHUB_TOKEN is not set", async () => {
    delete process.env.GITHUB_TOKEN;
    delete process.env.GITHUB_REPOS;

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    // Access private method via type assertion
    const events = await (service as unknown as HeartbeatPrivates).scrapeGitHub();
    expect(events).toEqual([]);
  });

  it("returns empty when GITHUB_REPOS is not set", async () => {
    process.env.GITHUB_TOKEN = "ghp_test";
    delete process.env.GITHUB_REPOS;

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const events = await (service as unknown as HeartbeatPrivates).scrapeGitHub();
    expect(events).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// compileEnemyWaves
// ---------------------------------------------------------------------------

describe("compileEnemyWaves", () => {
  it("returns empty for empty events", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const waves = (service as unknown as HeartbeatPrivates).compileEnemyWaves([]);
    expect(waves).toEqual([]);
  });

  it("groups events by source", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const events = [
      { source: "github", type: "pr_review_requested", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "github", type: "ci_failure", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "crm", type: "follow_up", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as unknown as HeartbeatPrivates).compileEnemyWaves(events);
    expect(waves).toHaveLength(2);

    const githubWave = waves.find((w: EnemyWave) => w.source === "github");
    const crmWave = waves.find((w: EnemyWave) => w.source === "crm");

    expect(githubWave).toBeDefined();
    expect(crmWave).toBeDefined();
    expect(githubWave!.events).toHaveLength(2);
    expect(crmWave!.events).toHaveLength(1);
  });

  it("marks escalation events as alerts", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const events = [
      { source: "tickets", type: "escalation", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "tickets", type: "normal", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as unknown as HeartbeatPrivates).compileEnemyWaves(events);
    expect(waves).toHaveLength(1);
    expect(waves[0].kind).toBe("alert");
  });

  it("marks sla_breach events as alerts", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const events = [
      { source: "support", type: "sla_breach", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as unknown as HeartbeatPrivates).compileEnemyWaves(events);
    expect(waves[0].kind).toBe("alert");
  });

  it("marks non-urgent events as enemy_wave", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const events = [
      { source: "github", type: "pr_review_requested", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as unknown as HeartbeatPrivates).compileEnemyWaves(events);
    expect(waves[0].kind).toBe("enemy_wave");
  });
});

// ---------------------------------------------------------------------------
// dispatch (WebSocket)
// ---------------------------------------------------------------------------

describe("dispatch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.AUTO_DISPATCH_ENABLED;
    delete process.env.WORKER_API_TOKEN;
    delete process.env.NEXUS_API_URL;
    delete process.env.GATEWAY_TENANT_ORG_ID;
    delete process.env.TENANT_ORG;
    delete process.env.STAGING_TENANT_ORG;
    delete process.env.PLATFORM_ORG_ID;
  });

  it("sends wave messages via WebSocket", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const mockWs = {
      readyState: 1, // WebSocket.OPEN
      send: vi.fn(),
      removeAllListeners: vi.fn(),
      close: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
    };

    // Inject mock websocket
    (service as unknown as HeartbeatPrivates).ws = mockWs;

    const waves = [
      {
        kind: "enemy_wave",
        source: "github",
        events: [{ source: "github", type: "pr_review_requested", payload: {}, timestamp: "" }],
        compiledAt: "2026-03-06T00:00:00Z",
      },
    ];

    await (service as unknown as HeartbeatPrivates).dispatch(waves);

    expect(mockWs.send).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(mockWs.send.mock.calls[0][0]);
    expect(sent.type).toBe("gateway:wave");
    expect(sent.data.source).toBe("github");
  });

  it("auto-dispatches with an explicit tenant header", async () => {
    process.env.AUTO_DISPATCH_ENABLED = "true";
    process.env.WORKER_API_TOKEN = "worker-token";
    process.env.NEXUS_API_URL = "http://nexus-api";
    process.env.PLATFORM_ORG_ID = "madfam";
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", mockFetch);

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    const mockWs = {
      readyState: 1,
      send: vi.fn(),
      removeAllListeners: vi.fn(),
      close: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
    };
    (service as unknown as HeartbeatPrivates).ws = mockWs;

    await (service as unknown as HeartbeatPrivates).dispatch([
      {
        kind: "enemy_wave",
        source: "crm",
        events: [
          {
            source: "crm",
            type: "hot_lead",
            payload: { lead_id: "lead-1", contact_id: "contact-1", score: 91 },
            timestamp: "",
          },
        ],
        compiledAt: "2026-03-06T00:00:00Z",
      },
    ]);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://nexus-api/api/v1/swarms/dispatch",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer worker-token",
          "X-Selva-Tenant-Org": "madfam",
        }),
      })
    );
    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.graph_type).toBe("crm");
  });

  it("uses event tenant over the environment fallback", async () => {
    process.env.AUTO_DISPATCH_ENABLED = "true";
    process.env.WORKER_API_TOKEN = "worker-token";
    process.env.NEXUS_API_URL = "http://nexus-api";
    process.env.PLATFORM_ORG_ID = "madfam";
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", mockFetch);

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );
    (service as unknown as HeartbeatPrivates).ws = {
      readyState: 1,
      send: vi.fn(),
      removeAllListeners: vi.fn(),
      close: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
    };

    await (service as unknown as HeartbeatPrivates).dispatch([
      {
        kind: "enemy_wave",
        source: "crm",
        events: [
          {
            source: "crm",
            type: "lead_followup",
            payload: { org_id: "tenant-a", lead_id: "lead-2" },
            timestamp: "",
          },
        ],
        compiledAt: "2026-03-06T00:00:00Z",
      },
    ]);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://nexus-api/api/v1/swarms/dispatch",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Selva-Tenant-Org": "tenant-a",
        }),
      })
    );
  });

  it("skips auto-dispatch when no tenant org can be resolved", async () => {
    process.env.AUTO_DISPATCH_ENABLED = "true";
    process.env.WORKER_API_TOKEN = "worker-token";
    process.env.NEXUS_API_URL = "http://nexus-api";
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", mockFetch);

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );
    (service as unknown as HeartbeatPrivates).ws = {
      readyState: 1,
      send: vi.fn(),
      removeAllListeners: vi.fn(),
      close: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
    };

    await (service as unknown as HeartbeatPrivates).dispatch([
      {
        kind: "enemy_wave",
        source: "crm",
        events: [
          {
            source: "crm",
            type: "hot_lead",
            payload: { lead_id: "lead-3" },
            timestamp: "",
          },
        ],
        compiledAt: "2026-03-06T00:00:00Z",
      },
    ]);

    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("configures only API-supported auto-dispatch graph types", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const ctor = HeartbeatService as unknown as {
      AUTO_DISPATCH_RULES: Record<string, { graphType: string }>;
    };
    const supported = new Set([
      "sequential",
      "parallel",
      "coding",
      "research",
      "crm",
      "custom",
      "deployment",
      "puppeteer",
      "meeting",
      "billing",
      "accounting",
      "sales",
      "intelligence",
      "operations",
      "campaign",
      "calibration",
    ]);

    expect(Object.keys(ctor.AUTO_DISPATCH_RULES)).toContain("github:pr_review_requested");
    expect(Object.keys(ctor.AUTO_DISPATCH_RULES)).toContain("github:ci_failure");
    expect(Object.values(ctor.AUTO_DISPATCH_RULES).every((rule) => supported.has(rule.graphType))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Stat getters
// ---------------------------------------------------------------------------

describe("HeartbeatService stat getters", () => {
  it("lastTickTime is null before any tick", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    expect(service.lastTickTime).toBeNull();
  });

  it("totalTicks is 0 before any tick", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    expect(service.totalTicks).toBe(0);
  });

  it("nextTickTime is null when not started", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService(
      "ws://localhost:4300/api/v1/approvals/ws",
      "*/30 * * * *",
      mockLogger()
    );

    expect(service.nextTickTime).toBeNull();
  });
});
