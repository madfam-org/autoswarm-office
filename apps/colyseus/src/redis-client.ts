/**
 * Singleton Redis client for Colyseus with reconnect backoff.
 */
import { createClient, type RedisClientType } from "redis";
import { createLogger } from "@selva/config/logging";

const logger = createLogger({ service: "colyseus" }).child({ component: "redis" });

let client: RedisClientType | null = null;

export async function getRedisClient(): Promise<RedisClientType> {
  if (client) return client;

  const url = process.env.REDIS_URL ?? "redis://localhost:6379";
  client = createClient({ url });

  client.on("error", (err) => {
    logger.error({ err }, "Redis client error");
  });

  client.on("reconnecting", () => {
    logger.info("Redis client reconnecting...");
  });

  await client.connect();
  logger.info({ url: url.replace(/\/\/.*@/, "//***@") }, "Redis client connected");

  return client;
}

export async function closeRedisClient(): Promise<void> {
  if (client) {
    await client.quit().catch(() => {});
    client = null;
  }
}
