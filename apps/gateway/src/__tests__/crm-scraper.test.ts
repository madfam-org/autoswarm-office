import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { CRMScraper } from "../crm-scraper";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function tRPCResponse<T>(data: T) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ result: { data } }),
  };
}

describe("CRMScraper", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    mockFetch.mockReset();
  });

  it("converts open leads to lead_followup events", async () => {
    mockFetch.mockResolvedValueOnce(
      tRPCResponse([
        {
          id: "l1",
          contact_id: "c1",
          stage_id: "s1",
          stage_name: "Discovery",
          score: 50,
          status: "open",
        },
      ])
    );
    // Activities call returns empty
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));

    const scraper = new CRMScraper("http://crm:3000", "token");
    const events = await scraper.scrape();

    const followups = events.filter((e) => e.type === "lead_followup");
    expect(followups).toHaveLength(1);
    expect(followups[0]!.source).toBe("crm");
    expect(followups[0]!.payload.lead_id).toBe("l1");
  });

  it("converts high-score leads to hot_lead events", async () => {
    mockFetch.mockResolvedValueOnce(
      tRPCResponse([
        {
          id: "l2",
          contact_id: "c2",
          stage_id: "s2",
          score: 95,
          status: "open",
        },
      ])
    );
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));

    const scraper = new CRMScraper("http://crm:3000");
    const events = await scraper.scrape();

    const hotLeads = events.filter((e) => e.type === "hot_lead");
    expect(hotLeads).toHaveLength(1);
    expect(hotLeads[0]!.payload.score).toBe(95);
  });

  it("converts overdue activities to activity_overdue events", async () => {
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));
    mockFetch.mockResolvedValueOnce(
      tRPCResponse([
        {
          id: "a1",
          type: "task",
          title: "Follow up call",
          status: "pending",
          due_date: "2020-01-01T00:00:00Z",
          entity_type: "contact",
          entity_id: "c1",
        },
      ])
    );

    const scraper = new CRMScraper("http://crm:3000");
    const events = await scraper.scrape();

    const overdue = events.filter((e) => e.type === "activity_overdue");
    expect(overdue).toHaveLength(1);
    expect(overdue[0]!.payload.title).toBe("Follow up call");
  });

  it("returns empty when CRM is unreachable", async () => {
    mockFetch.mockRejectedValue(new Error("Connection refused"));

    const scraper = new CRMScraper("http://crm:3000");
    const events = await scraper.scrape();

    expect(events).toEqual([]);
  });

  it("event format includes required fields", async () => {
    mockFetch.mockResolvedValueOnce(
      tRPCResponse([
        {
          id: "l1",
          contact_id: "c1",
          stage_id: "s1",
          status: "open",
          score: 30,
        },
      ])
    );
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));

    const scraper = new CRMScraper("http://crm:3000");
    const events = await scraper.scrape();

    expect(events).toHaveLength(1);
    const event = events[0]!;
    expect(event).toHaveProperty("source");
    expect(event).toHaveProperty("type");
    expect(event).toHaveProperty("payload");
    expect(event).toHaveProperty("timestamp");
    expect(typeof event.timestamp).toBe("string");
  });

  it("sends auth header when token is provided", async () => {
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));
    mockFetch.mockResolvedValueOnce(tRPCResponse([]));

    const scraper = new CRMScraper("http://crm:3000", "my-token");
    await scraper.scrape();

    expect(mockFetch).toHaveBeenCalled();
    const firstCall = mockFetch.mock.calls[0];
    const headers = firstCall?.[1]?.headers ?? {};
    expect(headers["Authorization"]).toBe("Bearer my-token");
  });
});
