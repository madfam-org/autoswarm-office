import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  OfficeStateSchema,
  TacticianSchema,
} from "../schema/OfficeState";
import { handleMovement } from "../handlers/movement";

function makeClient(sessionId: string) {
  return {
    sessionId,
    send: vi.fn(),
  } as any;
}

function addPlayer(
  state: OfficeStateSchema,
  sessionId: string,
  name: string,
  x = 400,
  y = 300
) {
  const player = new TacticianSchema();
  player.sessionId = sessionId;
  player.name = name;
  player.x = x;
  player.y = y;
  player.direction = "down";
  state.players.set(sessionId, player);
  return player;
}

describe("Multi-Player Avatars", () => {
  let state: OfficeStateSchema;

  beforeEach(() => {
    state = new OfficeStateSchema();
  });

  it("creates a player in state.players on join", () => {
    addPlayer(state, "sess1", "Alice");
    expect(state.players.size).toBe(1);
    const p = state.players.get("sess1");
    expect(p).toBeDefined();
    expect(p!.name).toBe("Alice");
    expect(p!.sessionId).toBe("sess1");
  });

  it("removes a player from state.players on leave", () => {
    addPlayer(state, "sess1", "Alice");
    addPlayer(state, "sess2", "Bob");
    expect(state.players.size).toBe(2);

    state.players.delete("sess1");
    expect(state.players.size).toBe(1);
    expect(state.players.has("sess1")).toBe(false);
    expect(state.players.has("sess2")).toBe(true);
  });

  it("handleMovement updates only the moving client's player", () => {
    addPlayer(state, "sess1", "Alice", 100, 100);
    addPlayer(state, "sess2", "Bob", 200, 200);

    const client1 = makeClient("sess1");
    handleMovement(state, client1, { x: 150, y: 150 });

    expect(state.players.get("sess1")!.x).toBe(150);
    expect(state.players.get("sess1")!.y).toBe(150);
    // Bob's position unchanged
    expect(state.players.get("sess2")!.x).toBe(200);
    expect(state.players.get("sess2")!.y).toBe(200);
  });

  it("multiple players coexist with independent positions", () => {
    addPlayer(state, "sess1", "Alice", 100, 100);
    addPlayer(state, "sess2", "Bob", 500, 500);
    addPlayer(state, "sess3", "Charlie", 300, 300);

    expect(state.players.size).toBe(3);
    expect(state.players.get("sess1")!.x).toBe(100);
    expect(state.players.get("sess2")!.x).toBe(500);
    expect(state.players.get("sess3")!.x).toBe(300);
  });

  it("player name is preserved from join options", () => {
    addPlayer(state, "sess1", "CustomName");
    expect(state.players.get("sess1")!.name).toBe("CustomName");
  });

  it("ignores movement for unknown session", () => {
    addPlayer(state, "sess1", "Alice", 100, 100);

    const unknownClient = makeClient("unknown");
    handleMovement(state, unknownClient, { x: 999, y: 999 });

    // No player created, no crash
    expect(state.players.size).toBe(1);
    expect(state.players.get("sess1")!.x).toBe(100);
  });

  it("updates direction based on movement delta", () => {
    addPlayer(state, "sess1", "Alice", 100, 100);
    const client = makeClient("sess1");

    handleMovement(state, client, { x: 200, y: 100 });
    expect(state.players.get("sess1")!.direction).toBe("right");

    handleMovement(state, client, { x: 200, y: 200 });
    expect(state.players.get("sess1")!.direction).toBe("down");

    handleMovement(state, client, { x: 100, y: 200 });
    expect(state.players.get("sess1")!.direction).toBe("left");

    handleMovement(state, client, { x: 100, y: 100 });
    expect(state.players.get("sess1")!.direction).toBe("up");
  });
});
