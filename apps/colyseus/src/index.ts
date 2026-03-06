import "dotenv/config";
import express from "express";
import { Server } from "@colyseus/core";
import { WebSocketTransport } from "@colyseus/ws-transport";
import { OfficeRoom } from "./rooms/OfficeRoom";

const PORT = Number(process.env.COLYSEUS_PORT ?? 4303);

const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "healthy", service: "colyseus" });
});

const server = new Server({
  transport: new WebSocketTransport({ server: app.listen(PORT) }),
});

server.define("office", OfficeRoom);

console.log(`[colyseus] Room server listening on port ${PORT}`);
console.log(`[colyseus] Health check available at http://localhost:${PORT}/health`);
console.log(`[colyseus] Office room registered and ready for connections`);
