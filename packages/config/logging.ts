/**
 * Shared pino logger factory for Selva TypeScript services.
 */

import pino from "pino";

export interface LoggerOptions {
  service: string;
  level?: string;
}

export function createLogger(options: LoggerOptions): pino.Logger {
  const level = options.level ?? process.env.LOG_LEVEL ?? "info";
  const isProduction = process.env.LOG_FORMAT !== "console" && process.env.NODE_ENV !== "development";

  return pino({
    name: options.service,
    level,
    ...(isProduction
      ? {
          formatters: {
            level(label: string) {
              return { level: label };
            },
          },
          timestamp: pino.stdTimeFunctions.isoTime,
        }
      : {
          transport: {
            target: "pino-pretty",
            options: {
              colorize: true,
              translateTime: "SYS:standard",
              ignore: "pid,hostname",
            },
          },
        }),
  });
}
