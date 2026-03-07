import "dotenv/config";
import express from "express";
import { Server } from "@colyseus/core";
import { WebSocketTransport } from "@colyseus/ws-transport";
import { OfficeRoom } from "./rooms/OfficeRoom";

const PORT = Number(process.env.COLYSEUS_PORT ?? 4303);
const NEXUS_API_URL = process.env.NEXUS_API_URL ?? "http://localhost:4300";

const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "healthy", service: "colyseus" });
});

const server = new Server({
  transport: new WebSocketTransport({ server: app.listen(PORT) }),
});

server.define("office", OfficeRoom, { nexusApiUrl: NEXUS_API_URL });

console.log(`[colyseus] Room server listening on port ${PORT}`);
console.log(`[colyseus] Health check available at http://localhost:${PORT}/health`);
console.log(`[colyseus] Office room registered and ready for connections`);
