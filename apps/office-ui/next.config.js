/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  transpilePackages: ['@selva/ui', '@selva/shared-types', '@janua/nextjs-sdk'],
  experimental: {
    clientTraceMetadata: ['sentry-trace', 'baggage'],
  },
};

if (process.env.SENTRY_AUTH_TOKEN && process.env.SENTRY_ORG) {
  const { withSentryConfig } = require('@sentry/nextjs');

  module.exports = withSentryConfig(nextConfig, {
    org: process.env.SENTRY_ORG,
    project: process.env.SENTRY_PROJECT || 'selva-office-ui',
    url: process.env.SENTRY_URL || 'https://sentry.io/',
    authToken: process.env.SENTRY_AUTH_TOKEN,
    silent: !process.env.CI,
    widenClientFileUpload: true,
    tunnelRoute: '/monitoring',
    webpack: {
      treeshake: {
        removeDebugLogging: true,
      },
      automaticVercelMonitors: false,
    },
  });
} else {
  module.exports = nextConfig;
}
