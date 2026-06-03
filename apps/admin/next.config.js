/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  transpilePackages: ['@selva/ui', '@selva/shared-types', '@janua/nextjs-sdk'],
};
module.exports = nextConfig;
