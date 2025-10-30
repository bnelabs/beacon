/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        'bne-ink': '#0E1B3A',
        'bne-steel': '#1F2C4A',
        'bne-silver': '#CBD4E6',
        'bne-ice': '#F5F7FA',
        'bne-azure': '#4EA8DE',
        'bne-emerald': '#3ED2A1',
        'bne-amber': '#F5B942'
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        'bne-panel': '0 24px 60px rgba(10, 20, 45, 0.28)'
      },
      backdropBlur: {
        halo: '18px'
      }
    }
  },
  plugins: []
}
