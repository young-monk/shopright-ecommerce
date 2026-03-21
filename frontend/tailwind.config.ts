import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#F96302',
          dark: '#d95200',
          light: '#ff7a2e',
        },
        secondary: {
          DEFAULT: '#1C2B39',
        },
      },
    },
  },
  plugins: [],
}
export default config
