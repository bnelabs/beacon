export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      /**
       * BEACON design tokens — "field report" palette.
       *
       * Warm paper surfaces, ink typography, a pine-green brand and an
       * ochre→rust→clay risk scale. Deliberately no blue and no dark
       * chrome: the platform is read like a supervisory briefing, on
       * paper-white, in daylight.
       *
       * Every token referenced anywhere in src/ must be defined here —
       * undefined `bne-*` utilities are silently dropped by Tailwind,
       * which is how the previous theme shipped ~170 dead border/shadow
       * classes (bne-frost, bne-indigo, bne-sky, shadow-bne-card).
       */
      colors: {
        bne: {
          // Surfaces
          paper: {
            DEFAULT: '#F6F2E9', // app background, warm paper
            dim: '#ECE5D4',     // recessed wells, table headers
            raise: '#FBF8F0'    // raised strips
          },
          card: '#FCFAF4',      // card surface
          line: {
            DEFAULT: '#E2DAC8', // hairline borders
            soft: '#EBE5D6',    // lighter dividers
            strong: '#CFC3A9'   // emphasized rules
          },
          // Text
          ink: {
            DEFAULT: '#26211A', // primary text, warm near-black
            soft: '#4A4335',    // strong secondary
            50: '#F2EEE3'       // ink-tint wash
          },
          muted: {
            DEFAULT: '#6E6653', // secondary text
            600: '#57503F'      // hover/pressed secondary
          },
          faint: '#948A72',     // tertiary text, placeholders
          chalk: '#FBF8F1',     // warm white text on saturated fills
          // Brand
          pine: {
            50: '#E9EFEA',
            100: '#D6E1D8',
            DEFAULT: '#2C5545',
            600: '#24483A',
            700: '#1B382C'
          },
          // Risk + status scale (mirrors RISK_COLORS in data/network-connections.js)
          moss: {   // OK / low risk
            50: '#EDF1E3',
            DEFAULT: '#55703B',
            600: '#455C2F'
          },
          ochre: {  // caution / moderate risk
            50: '#F6EDD7',
            DEFAULT: '#A87C1D',
            600: '#8C6615'
          },
          rust: {   // elevated / high risk
            50: '#F7E5D8',
            DEFAULT: '#BE5F2E',
            600: '#9E4C22'
          },
          clay: {   // breach / critical risk
            50: '#F4E0D8',
            DEFAULT: '#A33D22',
            600: '#87311B',
            700: '#6E2816'
          },
          stone: {  // neutral / uncalibrated
            DEFAULT: '#8A8168',
            50: '#EFEBE0'
          }
        }
      },
      fontFamily: {
        // Display: editorial serif for the wordmark, page titles and figures
        // of record. Loads Source Serif 4 when online; Georgia-class fallbacks
        // keep the identity offline.
        display: ['"Source Serif 4"', 'Georgia', '"Iowan Old Style"', '"Palatino Linotype"', 'Palatino', 'serif'],
        sans: ['ui-sans-serif', '-apple-system', '"Segoe UI Variable Text"', '"Segoe UI"', 'system-ui', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', '"JetBrains Mono"', '"Cascadia Mono"', 'Menlo', 'Consolas', 'monospace']
      },
      fontSize: {
        micro: ['10.5px', { lineHeight: '14px', letterSpacing: '0.09em' }]
      },
      letterSpacing: {
        micro: '0.09em',
        brand: '0.14em'
      },
      borderRadius: {
        DEFAULT: '4px'
      },
      boxShadow: {
        // Hairline-first: depth comes from rules, not drop shadows.
        'bne-panel': '0 1px 2px rgba(38, 33, 26, 0.05)',
        'bne-card': '0 2px 6px rgba(38, 33, 26, 0.08), 0 1px 2px rgba(38, 33, 26, 0.04)',
        'bne-lift': '0 8px 24px rgba(38, 33, 26, 0.12), 0 2px 6px rgba(38, 33, 26, 0.06)'
      }
    }
  },
  plugins: []
}
