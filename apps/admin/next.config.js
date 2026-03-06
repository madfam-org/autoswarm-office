/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  transpilePackages: ['@autoswarm/ui', '@autoswarm/shared-types'],
};
module.exports = nextConfig;
