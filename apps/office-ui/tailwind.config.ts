import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
    '../../packages/ui/src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        pixelFont: ['"Press Start 2P"', 'monospace'],
      },
      colors: {
        retro: {
          bg: '#0f172a',
          panel: '#1e293b',
          border: '#475569',
          accent: '#6366f1',
          gold: '#fbbf24',
          hp: '#22c55e',
          mp: '#3b82f6',
          xp: '#a855f7',
        },
      },
      boxShadow: {
        pixel:
          '0 0 0 2px #000, 0 0 0 4px #475569, inset 0 0 0 1px rgba(255,255,255,0.08)',
        'pixel-accent':
          '0 0 0 2px #000, 0 0 0 4px #6366f1, inset 0 0 0 1px rgba(255,255,255,0.1)',
      },
      animation: {
        'pixel-blink': 'pixelBlink 1s step-end infinite',
      },
      keyframes: {
        pixelBlink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
