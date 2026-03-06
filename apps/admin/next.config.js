/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  transpilePackages: ['@autoswarm/ui', '@autoswarm/shared-types', '@janua/nextjs-sdk'],
};
module.exports = nextConfig;
