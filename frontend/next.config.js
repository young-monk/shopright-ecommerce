/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'storage.googleapis.com' },
      { protocol: 'https', hostname: 'placehold.co' },
      { protocol: 'https', hostname: 'picsum.photos' },
    ],
  },
  async rewrites() {
    const apiGateway = process.env.API_GATEWAY_URL || 'http://api-gateway:8000'
    const chatbot   = process.env.CHATBOT_SERVICE_URL || 'http://chatbot:8004'
    return [
      { source: '/api-proxy/:path*',     destination: `${apiGateway}/:path*` },
      { source: '/chatbot-proxy/:path*', destination: `${chatbot}/:path*`    },
    ]
  },
};

module.exports = nextConfig;
