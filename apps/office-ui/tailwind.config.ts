import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
    '../../packages/ui/src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    screens: {
      xs: '360px',
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
      '2xl': '1536px',
      landscape: { raw: '(orientation: landscape) and (max-height: 500px)' },
    },
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
        // ── Tropical solarpunk day/night ──────────────────────────────
        // The primitive palettes are re-pointed at theme variables
        // (globals.css) so every existing slate-* / indigo-* /
        // text-white class follows the active data-theme. Night keeps
        // the historical dark reading; day inverts the tone ramp.
        slate: {
          50: 'rgb(var(--tone-50) / <alpha-value>)',
          100: 'rgb(var(--tone-100) / <alpha-value>)',
          200: 'rgb(var(--tone-200) / <alpha-value>)',
          300: 'rgb(var(--tone-300) / <alpha-value>)',
          400: 'rgb(var(--tone-400) / <alpha-value>)',
          500: 'rgb(var(--tone-500) / <alpha-value>)',
          600: 'rgb(var(--tone-600) / <alpha-value>)',
          700: 'rgb(var(--tone-700) / <alpha-value>)',
          800: 'rgb(var(--tone-800) / <alpha-value>)',
          900: 'rgb(var(--tone-900) / <alpha-value>)',
          950: 'rgb(var(--tone-950) / <alpha-value>)',
        },
        white: 'rgb(var(--base-white) / <alpha-value>)',
        indigo: {
          100: 'rgb(var(--accent-100) / <alpha-value>)',
          200: 'rgb(var(--accent-200) / <alpha-value>)',
          300: 'rgb(var(--accent-300) / <alpha-value>)',
          400: 'rgb(var(--accent-400) / <alpha-value>)',
          500: 'rgb(var(--accent-500) / <alpha-value>)',
          600: 'rgb(var(--accent-600) / <alpha-value>)',
          700: 'rgb(var(--accent-700) / <alpha-value>)',
        },
        // Semantic aliases for NEW components (preferred over raw tones).
        surface: {
          DEFAULT: 'rgb(var(--surface) / <alpha-value>)',
          raised: 'rgb(var(--surface-raised) / <alpha-value>)',
          overlay: 'rgb(var(--surface-overlay) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--ink) / <alpha-value>)',
          muted: 'rgb(var(--ink-muted) / <alpha-value>)',
        },
        edge: 'rgb(var(--edge) / <alpha-value>)',
        accent: {
          DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
          fg: 'rgb(var(--accent-fg) / <alpha-value>)',
        },
        solar: 'rgb(var(--solar) / <alpha-value>)',
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
        solarpunk: {
          wood: '#8b7355',
          'wood-dark': '#6b5a42',
          'wood-light': '#a89878',
          bamboo: '#c8b896',
          'bamboo-light': '#e8dcc4',
          moss: '#4a9e6e',
          'moss-dark': '#2d7a4a',
          leaf: '#68b684',
          'leaf-light': '#a8d8b9',
          solar: '#f6d55c',
          'solar-dark': '#d4a43a',
          sky: '#87ceeb',
          earth: '#5d4037',
          glass: '#a8dadc',
          bloom: '#ff6f61',
          glow: '#a8d8b9',
          sand: '#9a8a6a',
        },
        // Pixelact-compatible CSS variable references (scoped under .pixelact)
        pixelact: {
          bg: 'var(--pixelact-bg, #1e293b)',
          fg: 'var(--pixelact-fg, #f8fafc)',
          border: 'var(--pixelact-border, #475569)',
          primary: 'var(--pixelact-primary, #6366f1)',
          'primary-fg': 'var(--pixelact-primary-fg, #ffffff)',
          muted: 'var(--pixelact-muted, #334155)',
          'muted-fg': 'var(--pixelact-muted-fg, #94a3b8)',
          accent: 'var(--pixelact-accent, #818cf8)',
        },
      },
      // Z-index design system:
      //  - backdrop-below-hud (19): panel backdrops that sit *below* the HUD
      //    chrome (DashboardPanel, OpsFeed sliding panels). Click-to-close
      //    layer; must not occlude the HUD toggle buttons.
      //  - hud (20): top-level HUD chrome and persistent in-canvas overlays.
      //  - video (30): proximity-video bubbles (above HUD, below dialogs).
      //  - backdrop (40): full-screen dim backdrop for non-modal overlays
      //    (CoWebsitePanel sliding iframe, SkillMarketplace).
      //  - modal-backdrop (49): dim backdrop that pairs with `modal`.
      //  - modal (50): centered modal dialogs (MetricsDashboard, ApprovalModal,
      //    AvatarEditor) and right-side drawers behaving as dialogs
      //    (ApprovalPanel, CalendarPanel, AdminPanel, TaskDispatchPanel).
      //  - toast (60): transient notifications. Must remain above all modals
      //    so action feedback is never hidden behind dialogs.
      //  - banner (70): demo/system banner. Sits above toast intentionally;
      //    Toast offsets itself when this banner is active so they coexist.
      zIndex: {
        'backdrop-below-hud': '19',
        hud: '20',
        video: '30',
        backdrop: '40',
        'modal-backdrop': '49',
        modal: '50',
        toast: '60',
        banner: '70',
      },
      boxShadow: {
        pixel:
          '0 0 0 2px #000, 0 0 0 4px #475569, inset 0 0 0 1px rgba(255,255,255,0.08)',
        'pixel-accent':
          '0 0 0 2px #000, 0 0 0 4px #6366f1, inset 0 0 0 1px rgba(255,255,255,0.1)',
        // Pixelact 3D press effects
        'pixelact-raised':
          '2px 2px 0px 0px #000, inset -1px -1px 0px 0px rgba(0,0,0,0.3), inset 1px 1px 0px 0px rgba(255,255,255,0.15)',
        'pixelact-pressed':
          'inset 2px 2px 0px 0px rgba(0,0,0,0.3), inset -1px -1px 0px 0px rgba(255,255,255,0.1)',
      },
    },
  },
  plugins: [],
};

export default config;
