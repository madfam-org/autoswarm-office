import { describe, it, expect } from "vitest";
import { validatePosition, checkProximity } from "../handlers/movement";

// Minimal mock matching AgentSchema shape used by checkProximity.
// The function only reads .x, .y, and the result is typed as AgentSchema,
// so we cast a plain object with the fields the tests actually inspect.
function makeAgent(overrides: {
  id: string;
  name: string;
  role: string;
  status?: string;
  x: number;
  y: number;
}) {
  return {
    id: overrides.id,
    name: overrides.name,
    role: overrides.role,
    status: overrides.status ?? "idle",
    level: 1,
    x: overrides.x,
    y: overrides.y,
  } as any; // Cast to satisfy AgentSchema parameter type
}

// ---------------------------------------------------------------------------
// validatePosition
// ---------------------------------------------------------------------------
describe("validatePosition", () => {
  describe("with default OFFICE_BOUNDS (0-1280 x 0-704)", () => {
    it("returns true for origin (0, 0)", () => {
      expect(validatePosition(0, 0)).toBe(true);
    });

    it("returns true for center of the office", () => {
      expect(validatePosition(640, 352)).toBe(true);
    });

    it("returns true for max corner (1280, 704)", () => {
      expect(validatePosition(1280, 704)).toBe(true);
    });

    it("returns false when x is below minimum", () => {
      expect(validatePosition(-1, 300)).toBe(false);
    });

    it("returns false when x is above maximum", () => {
      expect(validatePosition(1281, 300)).toBe(false);
    });

    it("returns false when y is below minimum", () => {
      expect(validatePosition(400, -1)).toBe(false);
    });

    it("returns false when y is above maximum", () => {
      expect(validatePosition(400, 705)).toBe(false);
    });

    it("returns false when both coordinates are out of bounds", () => {
      expect(validatePosition(-10, 800)).toBe(false);
    });

    it("returns false for NaN x", () => {
      expect(validatePosition(NaN, 100)).toBe(false);
    });

    it("returns false for NaN y", () => {
      expect(validatePosition(100, NaN)).toBe(false);
    });

    it("returns false for non-number x", () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      expect(validatePosition("foo" as any, 100)).toBe(false);
    });

    it("returns false for non-number y", () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      expect(validatePosition(100, undefined as any)).toBe(false);
    });
  });

  describe("with custom bounds", () => {
    const smallRoom = { minX: 10, minY: 10, maxX: 50, maxY: 50 };

    it("returns true for position inside custom bounds", () => {
      expect(validatePosition(25, 25, smallRoom)).toBe(true);
    });

    it("returns true at exact min boundary", () => {
      expect(validatePosition(10, 10, smallRoom)).toBe(true);
    });

    it("returns true at exact max boundary", () => {
      expect(validatePosition(50, 50, smallRoom)).toBe(true);
    });

    it("returns false for position outside custom bounds", () => {
      expect(validatePosition(5, 25, smallRoom)).toBe(false);
    });

    it("returns false when x exceeds custom max", () => {
      expect(validatePosition(51, 25, smallRoom)).toBe(false);
    });
  });
});

// ---------------------------------------------------------------------------
// checkProximity
// ---------------------------------------------------------------------------
describe("checkProximity", () => {
  const origin = { x: 100, y: 100 };

  it("returns empty array when no agents exist", () => {
    const result = checkProximity(origin, [], 64);
    expect(result).toEqual([]);
  });

  it("finds an agent within the threshold distance", () => {
    const agents = [
      makeAgent({ id: "a1", name: "NearBot", role: "coder", x: 120, y: 100 }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(1);
    expect(result[0].agent.id).toBe("a1");
    expect(result[0].distance).toBeCloseTo(20, 5);
  });

  it("excludes agents beyond the threshold distance", () => {
    const agents = [
      makeAgent({ id: "a1", name: "FarBot", role: "coder", x: 500, y: 500 }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(0);
  });

  it("includes agent exactly at threshold distance", () => {
    // Place agent exactly 64 units away on x-axis
    const agents = [
      makeAgent({
        id: "a1",
        name: "EdgeBot",
        role: "reviewer",
        x: 164,
        y: 100,
      }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(1);
    expect(result[0].distance).toBeCloseTo(64, 5);
  });

  it("sorts results by distance ascending", () => {
    const agents = [
      makeAgent({
        id: "far",
        name: "FarBot",
        role: "planner",
        x: 150,
        y: 100,
      }),
      makeAgent({
        id: "near",
        name: "NearBot",
        role: "coder",
        x: 110,
        y: 100,
      }),
      makeAgent({
        id: "mid",
        name: "MidBot",
        role: "reviewer",
        x: 130,
        y: 100,
      }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(3);
    expect(result[0].agent.id).toBe("near");
    expect(result[1].agent.id).toBe("mid");
    expect(result[2].agent.id).toBe("far");
    expect(result[0].distance).toBeLessThan(result[1].distance);
    expect(result[1].distance).toBeLessThan(result[2].distance);
  });

  it("calculates euclidean distance correctly for diagonal positions", () => {
    // Agent at (130, 140) relative to tactician at (100, 100)
    // distance = sqrt(30^2 + 40^2) = sqrt(900 + 1600) = sqrt(2500) = 50
    const agents = [
      makeAgent({
        id: "diag",
        name: "DiagBot",
        role: "researcher",
        x: 130,
        y: 140,
      }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(1);
    expect(result[0].distance).toBeCloseTo(50, 5);
  });

  it("uses custom threshold to narrow results", () => {
    const agents = [
      makeAgent({
        id: "a1",
        name: "Close",
        role: "coder",
        x: 105,
        y: 100,
      }),
      makeAgent({
        id: "a2",
        name: "Medium",
        role: "coder",
        x: 130,
        y: 100,
      }),
    ];
    // Threshold of 10 should only find the close agent (distance=5)
    const result = checkProximity(origin, agents, 10);
    expect(result).toHaveLength(1);
    expect(result[0].agent.id).toBe("a1");
  });

  it("includes agent at distance 0 (same position)", () => {
    const agents = [
      makeAgent({
        id: "same",
        name: "SameSpot",
        role: "support",
        x: 100,
        y: 100,
      }),
    ];
    const result = checkProximity(origin, agents, 64);
    expect(result).toHaveLength(1);
    expect(result[0].distance).toBe(0);
  });
});
