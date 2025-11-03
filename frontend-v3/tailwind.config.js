export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        'bne-azure': {
          DEFAULT: '#0066CC',
          50: '#E6F2FF',
          100: '#CCE5FF',
          500: '#0066CC',
          600: '#0052A3',
          700: '#003D7A'
        },
        'bne-ink': {
          DEFAULT: '#1A1A1A',
          50: '#F5F5F5',
          500: '#1A1A1A',
          600: '#0D0D0D'
        },
        'bne-steel': {
          DEFAULT: '#5A5A6F',
          50: '#F0F0F3',
          500: '#5A5A6F',
          600: '#484858'
        },
        'bne-ice': '#F5F7FA',
        'bne-silver': '#D1D5DB',
        'bne-cloud': '#FFFFFF',
        'bne-emerald': {
          DEFAULT: '#10B981',
          50: '#D1FAE5',
          500: '#10B981',
          600: '#059669'
        },
        'bne-amber': {
          DEFAULT: '#F59E0B',
          50: '#FEF3C7',
          500: '#F59E0B',
          600: '#D97706'
        },
        'bne-crimson': {
          DEFAULT: '#DC2626',
          50: '#FEE2E2',
          500: '#DC2626',
          600: '#B91C1C'
        }
      },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        'bne-panel': '0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)',
        'bne-hover': '0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.06)'
      },
      backdropBlur: {
        'halo': '12px'
      }
    }
  },
  plugins: []
}
