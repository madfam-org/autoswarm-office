import * as path from "node:path";
import dotenv from "dotenv";

dotenv.config({ path: path.resolve(__dirname, "../../../.env") });
dotenv.config(); // CWD fallback for Docker/production

import express from "express";
import { Server } from "@colyseus/core";
import { WebSocketTransport } from "@colyseus/ws-transport";
import { createLogger } from "@selva/config/logging";
import { OfficeRoom } from "./rooms/OfficeRoom";

const logger = createLogger({ service: "colyseus" });

const PORT = Number(process.env.COLYSEUS_PORT ?? 4303);
const NEXUS_API_URL = process.env.NEXUS_API_URL ?? "http://localhost:4300";

const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "healthy", service: "colyseus" });
});

const server = new Server({
  transport: new WebSocketTransport({
    server: app.listen(PORT),
    maxPayload: 1024 * 1024, // 1 MB — default is too small for state with agents
  }),
});

server
  .define("office", OfficeRoom, { nexusApiUrl: NEXUS_API_URL })
  .filterBy(["orgId"]);

logger.info({ port: PORT }, "Room server listening");
logger.info({ url: `http://localhost:${PORT}/health` }, "Health check available");
logger.info("Office room registered and ready for connections");
