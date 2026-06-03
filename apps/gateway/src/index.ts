import * as path from "node:path";
import dotenv from "dotenv";

dotenv.config({ path: path.resolve(__dirname, "../../../.env") });
dotenv.config(); // CWD fallback for Docker/production

import http from "node:http";
import { createLogger } from "@selva/config/logging";
import { initSentry } from "@selva/config/sentry";
import { HeartbeatService } from "./heartbeat";
import { MemoryManager } from "./memory";

const logger = createLogger({ service: "gateway" });

initSentry({ service: "gateway" });

const NEXUS_API_URL =
  process.env.NEXUS_API_WS_URL ?? "ws://localhost:4300/api/v1/approvals/ws";
const CRON_EXPRESSION = process.env.HEARTBEAT_CRON ?? "*/30 * * * *";
const MEMORY_DIR = process.env.MEMORY_DIR ?? "./data/memory";
const HEALTH_PORT = parseInt(process.env.GATEWAY_HEALTH_PORT ?? "4304", 10);

const heartbeatLogger = logger.child({ component: "heartbeat" });
const memoryLogger = logger.child({ component: "memory" });

const heartbeat = new HeartbeatService(
  NEXUS_API_URL,
  CRON_EXPRESSION,
  heartbeatLogger
);
const memory = new MemoryManager(MEMORY_DIR, memoryLogger);

function createHealthServer(): http.Server {
  const server = http.createServer((req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      const body = JSON.stringify({
        status: "ok",
        service: "selva-gateway",
        version: "0.1.0",
        uptime: process.uptime(),
        heartbeat: {
          lastTickTime: heartbeat.lastTickTime,
          nextTickTime: heartbeat.nextTickTime,
          totalTicks: heartbeat.totalTicks,
        },
        timestamp: new Date().toISOString(),
      });

      res.writeHead(200, {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
      });
      res.end(body);
      return;
    }

    if (req.method === "GET" && req.url === "/metrics") {
      res.writeHead(200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
      });
      res.end("");
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Not Found" }));
  });

  return server;
}

async function main(): Promise<void> {
  logger.info("Selva OpenClaw gateway starting...");

  memory.ensureDir();
  logger.info({ memoryDir: MEMORY_DIR }, "Memory directory initialized");

  const soul = memory.readSoul();
  if (soul) {
    logger.info("SOUL.md loaded successfully");
  } else {
    logger.info("No SOUL.md found; operating with default personality");
  }

  heartbeat.start();
  logger.info({ cronExpression: CRON_EXPRESSION }, "HeartbeatService started");

  const healthServer = createHealthServer();
  healthServer.listen(HEALTH_PORT, () => {
    logger.info({ port: HEALTH_PORT }, "Health server listening");
  });

  memory.appendToMemory("Gateway started");
  logger.info("OpenClaw gateway is running");
}

function shutdown(signal: string): void {
  logger.info({ signal }, "Received signal, shutting down gracefully...");

  heartbeat.stop();
  memory.appendToMemory("Gateway stopped");

  logger.info("Shutdown complete");
  process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

main().catch((err) => {
  logger.fatal({ err }, "Fatal error during startup");
  process.exit(1);
});
