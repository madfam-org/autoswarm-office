import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// We test the HeartbeatService methods by importing the class and mocking
// external dependencies (Octokit, WebSocket).

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
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    // Access private method via type assertion
    const events = await (service as any).scrapeGitHub();
    expect(events).toEqual([]);
  });

  it("returns empty when GITHUB_REPOS is not set", async () => {
    process.env.GITHUB_TOKEN = "ghp_test";
    delete process.env.GITHUB_REPOS;

    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const events = await (service as any).scrapeGitHub();
    expect(events).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// compileEnemyWaves
// ---------------------------------------------------------------------------

describe("compileEnemyWaves", () => {
  it("returns empty for empty events", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const waves = (service as any).compileEnemyWaves([]);
    expect(waves).toEqual([]);
  });

  it("groups events by source", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const events = [
      { source: "github", type: "pr_review_requested", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "github", type: "ci_failure", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "crm", type: "follow_up", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as any).compileEnemyWaves(events);
    expect(waves).toHaveLength(2);

    const githubWave = waves.find((w: any) => w.source === "github");
    const crmWave = waves.find((w: any) => w.source === "crm");

    expect(githubWave.events).toHaveLength(2);
    expect(crmWave.events).toHaveLength(1);
  });

  it("marks escalation events as alerts", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const events = [
      { source: "tickets", type: "escalation", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
      { source: "tickets", type: "normal", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as any).compileEnemyWaves(events);
    expect(waves).toHaveLength(1);
    expect(waves[0].kind).toBe("alert");
  });

  it("marks sla_breach events as alerts", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const events = [
      { source: "support", type: "sla_breach", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as any).compileEnemyWaves(events);
    expect(waves[0].kind).toBe("alert");
  });

  it("marks non-urgent events as enemy_wave", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const events = [
      { source: "github", type: "pr_review_requested", payload: {}, timestamp: "2026-03-06T00:00:00Z" },
    ];

    const waves = (service as any).compileEnemyWaves(events);
    expect(waves[0].kind).toBe("enemy_wave");
  });
});

// ---------------------------------------------------------------------------
// dispatch (WebSocket)
// ---------------------------------------------------------------------------

describe("dispatch", () => {
  it("sends wave messages via WebSocket", async () => {
    const { HeartbeatService } = await import("../heartbeat");
    const service = new HeartbeatService("ws://localhost:4300/api/v1/approvals/ws");

    const mockWs = {
      readyState: 1, // WebSocket.OPEN
      send: vi.fn(),
      removeAllListeners: vi.fn(),
      close: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
    };

    // Inject mock websocket
    (service as any).ws = mockWs;

    const waves = [
      {
        kind: "enemy_wave",
        source: "github",
        events: [{ source: "github", type: "pr_review_requested", payload: {}, timestamp: "" }],
        compiledAt: "2026-03-06T00:00:00Z",
      },
    ];

    await (service as any).dispatch(waves);

    expect(mockWs.send).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(mockWs.send.mock.calls[0][0]);
    expect(sent.type).toBe("gateway:wave");
    expect(sent.data.source).toBe("github");
  });
});
