import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  OfficeStateSchema,
  TacticianSchema,
} from "../schema/OfficeState";
import { handleChat, addSystemMessage } from "../handlers/chat";

function makeClient(sessionId: string) {
  return {
    sessionId,
    send: vi.fn(),
  } as any;
}

function addPlayer(state: OfficeStateSchema, sessionId: string, name: string) {
  const player = new TacticianSchema();
  player.sessionId = sessionId;
  player.name = name;
  player.x = 400;
  player.y = 300;
  player.direction = "down";
  state.players.set(sessionId, player);
}

describe("Chat System", () => {
  let state: OfficeStateSchema;

  beforeEach(() => {
    state = new OfficeStateSchema();
  });

  it("creates a chat message with correct fields", () => {
    addPlayer(state, "sess1", "Alice");
    const client = makeClient("sess1");

    handleChat(state, client, { content: "Hello world" });

    expect(state.chatMessages.length).toBe(1);
    const msg = state.chatMessages.at(0)!;
    expect(msg.senderSessionId).toBe("sess1");
    expect(msg.senderName).toBe("Alice");
    expect(msg.content).toBe("Hello world");
    expect(msg.isSystem).toBe(false);
    expect(msg.id).toMatch(/^msg-/);
    expect(msg.timestamp).toBeGreaterThan(0);
  });

  it("rejects empty messages", () => {
    addPlayer(state, "sess1", "Alice");
    const client = makeClient("sess1");

    handleChat(state, client, { content: "" });

    expect(state.chatMessages.length).toBe(0);
    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_chat",
      message: "Message content cannot be empty",
    });
  });

  it("rejects whitespace-only messages", () => {
    addPlayer(state, "sess1", "Alice");
    const client = makeClient("sess1");

    handleChat(state, client, { content: "   " });

    expect(state.chatMessages.length).toBe(0);
    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_chat",
      message: "Message content cannot be empty",
    });
  });

  it("rejects messages exceeding 500 characters", () => {
    addPlayer(state, "sess1", "Alice");
    const client = makeClient("sess1");

    handleChat(state, client, { content: "x".repeat(501) });

    expect(state.chatMessages.length).toBe(0);
    expect(client.send).toHaveBeenCalledWith("error", {
      type: "invalid_chat",
      message: "Message exceeds 500 character limit",
    });
  });

  it("trims message history to 50 messages", () => {
    addPlayer(state, "sess1", "Alice");
    const client = makeClient("sess1");

    for (let i = 0; i < 55; i++) {
      handleChat(state, client, { content: `msg ${i}` });
    }

    expect(state.chatMessages.length).toBe(50);
    // The oldest messages should be trimmed
    expect(state.chatMessages.at(0)!.content).toBe("msg 5");
    expect(state.chatMessages.at(49)!.content).toBe("msg 54");
  });

  it("creates system messages correctly", () => {
    addSystemMessage(state, "Alice joined");

    expect(state.chatMessages.length).toBe(1);
    const msg = state.chatMessages.at(0)!;
    expect(msg.senderName).toBe("System");
    expect(msg.senderSessionId).toBe("");
    expect(msg.content).toBe("Alice joined");
    expect(msg.isSystem).toBe(true);
  });

  it("uses 'Unknown' for unregistered player sessions", () => {
    const client = makeClient("unknown-sess");

    handleChat(state, client, { content: "Hello" });

    expect(state.chatMessages.length).toBe(1);
    expect(state.chatMessages.at(0)!.senderName).toBe("Unknown");
  });
});
