import { useEffect, useRef, useCallback } from "react";
import { gameEventBus } from "@/game/PhaserGame";

interface ChatEvent {
  senderName: string;
  content: string;
  isSystem: boolean;
}

/**
 * Request desktop notification permission and show notifications for
 * chat messages when the tab is unfocused.
 *
 * Respects DND status — no notifications when player status is "dnd".
 */
export function useNotifications(
  playerName: string,
  playerStatus: string
): void {
  const permissionRef = useRef<NotificationPermission>("default");

  // Request permission on mount
  useEffect(() => {
    if (typeof Notification === "undefined") return;
    if (Notification.permission === "granted") {
      permissionRef.current = "granted";
      return;
    }
    if (Notification.permission === "default") {
      Notification.requestPermission().then((perm) => {
        permissionRef.current = perm;
      });
    }
  }, []);

  const handleChatMessage = useCallback(
    (event: Event) => {
      // Skip if tab is focused, DND, or no permission
      if (document.hasFocus()) return;
      if (playerStatus === "dnd") return;
      if (permissionRef.current !== "granted") return;

      const detail = (event as CustomEvent<ChatEvent>).detail;
      if (!detail || detail.isSystem) return;

      // Check for @mention
      const isMention = detail.content
        .toLowerCase()
        .includes(`@${playerName.toLowerCase()}`);

      const title = isMention
        ? `${detail.senderName} mentioned you`
        : `${detail.senderName}`;

      const body = detail.content.length > 120
        ? detail.content.slice(0, 117) + "..."
        : detail.content;

      new Notification(title, {
        body,
        tag: "selva-chat",
        icon: "/assets/icons/favicon-32.png",
      });
    },
    [playerName, playerStatus]
  );

  useEffect(() => {
    gameEventBus.addEventListener("chat-message", handleChatMessage);
    return () => {
      gameEventBus.removeEventListener("chat-message", handleChatMessage);
    };
  }, [handleChatMessage]);
}
