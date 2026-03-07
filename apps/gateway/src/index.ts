import "dotenv/config";
import { HeartbeatService } from "./heartbeat";
import { MemoryManager } from "./memory";

const NEXUS_API_URL =
  process.env.NEXUS_API_WS_URL ?? "ws://localhost:4300/api/v1/approvals/ws";
const CRON_EXPRESSION = process.env.HEARTBEAT_CRON ?? "*/30 * * * *";
const MEMORY_DIR = process.env.MEMORY_DIR ?? "./data/memory";

const heartbeat = new HeartbeatService(NEXUS_API_URL, CRON_EXPRESSION);
const memory = new MemoryManager(MEMORY_DIR);

async function main(): Promise<void> {
  console.log("[gateway] AutoSwarm OpenClaw gateway starting...");

  memory.ensureDir();
  console.log(`[gateway] Memory directory initialized at ${MEMORY_DIR}`);

  const soul = memory.readSoul();
  if (soul) {
    console.log("[gateway] SOUL.md loaded successfully");
  } else {
    console.log("[gateway] No SOUL.md found; operating with default personality");
  }

  heartbeat.start();
  console.log(
    `[gateway] HeartbeatService started with cron: ${CRON_EXPRESSION}`
  );

  memory.appendToMemory("Gateway started");
  console.log("[gateway] OpenClaw gateway is running");
}

function shutdown(signal: string): void {
  console.log(`[gateway] Received ${signal}, shutting down gracefully...`);

  heartbeat.stop();
  memory.appendToMemory("Gateway stopped");

  console.log("[gateway] Shutdown complete");
  process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

main().catch((err) => {
  console.error("[gateway] Fatal error during startup:", err);
  process.exit(1);
});
