import * as path from "node:path";
import dotenv from "dotenv";

dotenv.config({ path: path.resolve(__dirname, "../../../.env") });
dotenv.config(); // CWD fallback for Docker/production

import { createServer } from "node:http";
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

// The http server must NOT be pre-listened (`app.listen(...)`): the matchmake
// HTTP routes (`/matchmake/joinOrCreate/...`) are only bound inside
// `server.listen()`, which wraps the Express handler so Colyseus routes are
// served first and everything else falls through to Express. Pre-listening
// skipped that binding entirely — every join POST 404'd against Express and
// no client could ever enter the office.
const server = new Server({
  transport: new WebSocketTransport({
    server: createServer(app),
    maxPayload: 1024 * 1024, // 1 MB — default is too small for state with agents
  }),
});

server
  .define("office", OfficeRoom, { nexusApiUrl: NEXUS_API_URL })
  .filterBy(["orgId"]);

void server.listen(PORT).then(() => {
  logger.info({ port: PORT }, "Room server listening");
  logger.info({ url: `http://localhost:${PORT}/health` }, "Health check available");
  logger.info("Office room registered and ready for connections");
});
