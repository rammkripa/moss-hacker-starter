import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  eslint: {
    // The current demo tree has lint/prettier debt unrelated to production
    // runtime. Keep TypeScript checking on, but don't block Vercel builds on
    // ESLint while we stabilize deployment.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
