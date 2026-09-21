import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: '#0B0F19',
          panel: '#111826',
          panel2: '#161F2E',
          border: '#232E42',
        },
        accent: {
          teal: '#2DD4BF',
          amber: '#F5A524',
          blue: '#3B82F6',
          violet: '#A78BFA',
        },
        text: {
          primary: '#E5E9F0',
          secondary: '#94A3B8',
          muted: '#5B6B85',
        },
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
