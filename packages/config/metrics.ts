/**
 * Shared Prometheus metrics registry for Selva TypeScript services.
 */

export interface MetricsRegistryOptions {
  service: string;
  prefix?: string;
}

export function createMetricsRegistry(options: MetricsRegistryOptions) {
  // Dynamic import so prom-client is optional
  try {
    const client = require("prom-client");
    const registry = new client.Registry();
    registry.setDefaultLabels({ service: options.service });
    client.collectDefaultMetrics({ register: registry, prefix: options.prefix ?? "" });
    return { client, registry };
  } catch {
    // prom-client not installed — return stub
    return {
      client: null,
      registry: {
        metrics: async () => "",
        contentType: "text/plain",
        setDefaultLabels: () => {},
      },
    };
  }
}
