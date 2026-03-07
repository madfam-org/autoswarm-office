import { Client } from "@colyseus/core";
import { OfficeStateSchema, ChatMessageSchema } from "../schema/OfficeState";

const MAX_CONTENT_LENGTH = 500;
const MAX_MESSAGES = 50;

interface ChatData {
  content: string;
}

let messageCounter = 0;

function generateMessageId(): string {
  return `msg-${Date.now()}-${++messageCounter}`;
}

export function handleChat(
  state: OfficeStateSchema,
  client: Client,
  data: ChatData
): void {
  const content = typeof data.content === "string" ? data.content.trim() : "";

  if (content.length === 0) {
    client.send("error", {
      type: "invalid_chat",
      message: "Message content cannot be empty",
    });
    return;
  }

  if (content.length > MAX_CONTENT_LENGTH) {
    client.send("error", {
      type: "invalid_chat",
      message: `Message exceeds ${MAX_CONTENT_LENGTH} character limit`,
    });
    return;
  }

  const player = state.players.get(client.sessionId);
  const senderName = player?.name ?? "Unknown";

  const msg = new ChatMessageSchema();
  msg.id = generateMessageId();
  msg.senderSessionId = client.sessionId;
  msg.senderName = senderName;
  msg.content = content;
  msg.timestamp = Date.now();
  msg.isSystem = false;

  state.chatMessages.push(msg);

  // Trim to last MAX_MESSAGES
  while (state.chatMessages.length > MAX_MESSAGES) {
    state.chatMessages.deleteAt(0);
  }
}

export function addSystemMessage(
  state: OfficeStateSchema,
  content: string
): void {
  const msg = new ChatMessageSchema();
  msg.id = generateMessageId();
  msg.senderSessionId = "";
  msg.senderName = "System";
  msg.content = content;
  msg.timestamp = Date.now();
  msg.isSystem = true;

  state.chatMessages.push(msg);

  while (state.chatMessages.length > MAX_MESSAGES) {
    state.chatMessages.deleteAt(0);
  }
}
