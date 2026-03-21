/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    domains: ['storage.googleapis.com', 'placehold.co'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_CHATBOT_URL: process.env.NEXT_PUBLIC_CHATBOT_URL,
  },
};

module.exports = nextConfig;
