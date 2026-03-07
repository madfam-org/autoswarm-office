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
      fontSize: {
        'retro-xs': ['7px', { lineHeight: '12px' }],
        'retro-sm': ['8px', { lineHeight: '14px' }],
        'retro-base': ['10px', { lineHeight: '16px' }],
        'retro-lg': ['12px', { lineHeight: '18px' }],
      },
      colors: {
        semantic: {
          success: '#10b981',
          'success-light': '#34d399',
          'success-dark': '#047857',
          error: '#ef4444',
          'error-light': '#f87171',
          'error-dark': '#991b1b',
          warning: '#f59e0b',
          info: '#22d3ee',
        },
      },
      zIndex: {
        hud: '20',
        video: '30',
        backdrop: '40',
        modal: '50',
        toast: '60',
      },
      boxShadow: {
        pixel:
          '0 0 0 2px #000, 0 0 0 4px #475569, inset 0 0 0 1px rgba(255,255,255,0.08)',
        'pixel-accent':
          '0 0 0 2px #000, 0 0 0 4px #6366f1, inset 0 0 0 1px rgba(255,255,255,0.1)',
      },
    },
  },
  plugins: [],
};

export default config;
