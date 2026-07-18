import { Client } from "@colyseus/core";
import { OfficeStateSchema, ChatMessageSchema } from "../schema/OfficeState";

const MAX_CONTENT_LENGTH = 500;
const MAX_MESSAGES = 50;

const NEXUS_API_URL = process.env.NEXUS_API_URL || "http://localhost:4300";

interface ChatData {
  content: string;
}

/**
 * Bundle of auth context propagated from the OfficeRoom into the chat
 * handler. The nexus-api `/api/v1/chat/messages` endpoint requires Bearer
 * authentication AND a `X-Selva-Tenant-Org` header so that worker-token
 * calls are resolved to the correct tenant scope.
 */
export interface ChatAuthContext {
  /** Service-to-service Bearer token (worker shared-secret). */
  serviceToken: string;
  /** Tenant org_id for the room/player; threaded into X-Selva-Tenant-Org. */
  orgId: string;
}

let messageCounter = 0;

function generateMessageId(): string {
  return `msg-${Date.now()}-${++messageCounter}`;
}

/**
 * Fetch with retry: retries on network errors and 5xx responses.
 * Returns the response on success (< 500), or null after exhausting retries.
 */
async function fetchWithRetry(
  url: string,
  options: RequestInit,
  retries = 2,
  delays = [500, 1000],
): Promise<Response | null> {
  for (let i = 0; i < retries; i++) {
    try {
      const resp = await fetch(url, options);
      if (resp.ok || resp.status < 500) return resp;
    } catch {
      // network error, retry
    }
    if (i < retries - 1 && delays[i]) {
      await new Promise((r) => setTimeout(r, delays[i]));
    }
  }
  return null;
}

/**
 * Fire-and-forget POST to nexus-api to persist a chat message.
 *
 * Authenticated with the worker shared-secret token plus the
 * `X-Selva-Tenant-Org` header (per Wave 3B-A). The org_id is NOT placed
 * in the request body — the API derives it server-side from the
 * authenticated caller. This prevents Colyseus (or anything else holding
 * the worker token) from writing chat into a different tenant's history.
 *
 * If `auth.serviceToken` is empty (no `COLYSEUS_SERVICE_TOKEN` configured
 * and `DEV_AUTH_BYPASS` is not enabled) the call is skipped — better
 * visible breakage of chat persistence than a silent fallback that hits
 * the API unauthenticated and returns 401.
 *
 * Failures are logged in dev, never raised.
 */
function persistMessage(
  roomId: string,
  senderSessionId: string,
  senderName: string,
  content: string,
  isSystem: boolean,
  auth: ChatAuthContext | undefined
): void {
  if (!auth || !auth.serviceToken) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        "Skipping chat persistence: missing service token or auth context (set COLYSEUS_SERVICE_TOKEN or DEV_AUTH_BYPASS)"
      );
    }
    return;
  }

  fetchWithRetry(`${NEXUS_API_URL}/api/v1/chat/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${auth.serviceToken}`,
      "X-Selva-Tenant-Org": auth.orgId || "default",
    },
    body: JSON.stringify({
      room_id: roomId,
      sender_session_id: senderSessionId,
      sender_name: senderName,
      content,
      is_system: isSystem,
      // NOTE: org_id deliberately omitted — the server derives it from
      // the X-Selva-Tenant-Org header to prevent caller-controlled
      // cross-tenant writes.
    }),
  }).catch((err) => {
    if (process.env.NODE_ENV !== "production") {
      console.warn("Failed to persist chat message:", err.message);
    }
  });
}

export function handleChat(
  state: OfficeStateSchema,
  client: Client,
  data: ChatData,
  roomId: string = "office",
  auth?: ChatAuthContext
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
    state.chatMessages.shift();
  }

  // Fire-and-forget persistence (authenticated + tenant-scoped)
  persistMessage(roomId, client.sessionId, senderName, content, false, auth);
}

export function addSystemMessage(
  state: OfficeStateSchema,
  content: string,
  roomId: string = "office",
  auth?: ChatAuthContext
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
    state.chatMessages.shift();
  }

  // Fire-and-forget persistence (authenticated + tenant-scoped)
  persistMessage(roomId, "", "System", content, true, auth);
}
