/**
 * Shared Sentry initialization for Selva TypeScript services.
 */

export interface SentryOptions {
  service: string;
  dsn?: string;
  tracesSampleRate?: number;
}

export function initSentry(options: SentryOptions): void {
  const dsn = options.dsn ?? process.env.SENTRY_DSN;
  if (!dsn) return;

  try {
    // Dynamic import so @sentry/node is optional
    const Sentry = require("@sentry/node");
    const release = process.env.GIT_SHA ?? "unknown";

    Sentry.init({
      dsn,
      tracesSampleRate: options.tracesSampleRate ?? 0.1,
      release: `${options.service}@${release}`,
      environment: process.env.ENVIRONMENT ?? process.env.NODE_ENV ?? "production",
      serverName: options.service,
    });
  } catch {
    // @sentry/node not installed — skip
  }
}
