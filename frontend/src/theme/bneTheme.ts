/**
 * BNE Corporate Brand Theme
 * Professional financial technology design system
 */

export const bneColors = {
  // Primary - Deep Blue (Trust, Stability, Financial Authority)
  primary: {
    50: '#EFF6FF',
    100: '#DBEAFE',
    200: '#BFDBFE',
    300: '#93C5FD',
    400: '#60A5FA',
    500: '#3B82F6',
    600: '#2563EB',
    700: '#1D4ED8',
    800: '#1E40AF',
    900: '#1E3A8A',
    950: '#0F1F47',
  },

  // Secondary - Gold/Amber (Premium, Financial Excellence)
  secondary: {
    50: '#FFFBEB',
    100: '#FEF3C7',
    200: '#FDE68A',
    300: '#FCD34D',
    400: '#FBBF24',
    500: '#F59E0B',
    600: '#D97706',
    700: '#B45309',
    800: '#92400E',
    900: '#78350F',
  },

  // Accent - Teal (Technology, Innovation, Data)
  accent: {
    50: '#F0FDFA',
    100: '#CCFBF1',
    200: '#99F6E4',
    300: '#5EEAD4',
    400: '#2DD4BF',
    500: '#14B8A6',
    600: '#0D9488',
    700: '#0F766E',
    800: '#115E59',
    900: '#134E4A',
  },

  // Neutrals - Professional Dark Theme
  neutral: {
    0: '#FFFFFF',
    50: '#F8FAFC',
    100: '#F1F5F9',
    200: '#E2E8F0',
    300: '#CBD5E1',
    400: '#94A3B8',
    500: '#64748B',
    600: '#475569',
    700: '#334155',
    800: '#1E293B',
    900: '#0F172A',
    950: '#020617',
  },

  // Semantic Colors
  success: {
    light: '#10B981',
    main: '#059669',
    dark: '#047857',
  },
  warning: {
    light: '#F59E0B',
    main: '#D97706',
    dark: '#B45309',
  },
  error: {
    light: '#EF4444',
    main: '#DC2626',
    dark: '#B91C1C',
  },
  info: {
    light: '#3B82F6',
    main: '#2563EB',
    dark: '#1D4ED8',
  },
};

export const bneTypography = {
  fontFamily: {
    sans: [
      'Inter',
      '-apple-system',
      'BlinkMacSystemFont',
      'Segoe UI',
      'Roboto',
      'Helvetica Neue',
      'Arial',
      'sans-serif',
    ].join(','),
    mono: [
      'JetBrains Mono',
      'Fira Code',
      'SF Mono',
      'Monaco',
      'Cascadia Code',
      'Consolas',
      'monospace',
    ].join(','),
    display: [
      'Clash Display',
      'Inter',
      'system-ui',
      'sans-serif',
    ].join(','),
  },

  fontSize: {
    xs: '0.75rem',      // 12px
    sm: '0.875rem',     // 14px
    base: '1rem',       // 16px
    lg: '1.125rem',     // 18px
    xl: '1.25rem',      // 20px
    '2xl': '1.5rem',    // 24px
    '3xl': '1.875rem',  // 30px
    '4xl': '2.25rem',   // 36px
    '5xl': '3rem',      // 48px
    '6xl': '3.75rem',   // 60px
    '7xl': '4.5rem',    // 72px
  },

  fontWeight: {
    light: 300,
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
    extrabold: 800,
  },

  lineHeight: {
    tight: 1.25,
    normal: 1.5,
    relaxed: 1.75,
  },
};

export const bneSpacing = {
  xs: '0.25rem',   // 4px
  sm: '0.5rem',    // 8px
  md: '1rem',      // 16px
  lg: '1.5rem',    // 24px
  xl: '2rem',      // 32px
  '2xl': '3rem',   // 48px
  '3xl': '4rem',   // 64px
  '4xl': '6rem',   // 96px
};

export const bneBorderRadius = {
  none: '0',
  sm: '0.25rem',   // 4px
  md: '0.5rem',    // 8px
  lg: '0.75rem',   // 12px
  xl: '1rem',      // 16px
  '2xl': '1.5rem', // 24px
  full: '9999px',
};

export const bneShadows = {
  sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
  md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
  lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
  xl: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
  '2xl': '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
  inner: 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.06)',
  glow: {
    blue: '0 0 20px rgba(59, 130, 246, 0.5)',
    gold: '0 0 20px rgba(245, 158, 11, 0.5)',
    teal: '0 0 20px rgba(20, 184, 166, 0.5)',
  },
};

export const bneGradients = {
  primary: 'linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%)',
  secondary: 'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)',
  accent: 'linear-gradient(135deg, #14B8A6 0%, #0D9488 100%)',
  dark: 'linear-gradient(135deg, #0F172A 0%, #1E293B 100%)',
  premium: 'linear-gradient(135deg, #1E3A8A 0%, #F59E0B 50%, #14B8A6 100%)',
  glass: 'linear-gradient(135deg, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0.05) 100%)',
};

export const bneAnimations = {
  transition: {
    fast: '150ms ease-in-out',
    normal: '300ms ease-in-out',
    slow: '500ms ease-in-out',
  },
  duration: {
    fast: 150,
    normal: 300,
    slow: 500,
  },
  easing: {
    easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
    easeOut: 'cubic-bezier(0.0, 0, 0.2, 1)',
    easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
    sharp: 'cubic-bezier(0.4, 0, 0.6, 1)',
  },
};

export const bneBreakpoints = {
  xs: '320px',
  sm: '640px',
  md: '768px',
  lg: '1024px',
  xl: '1280px',
  '2xl': '1536px',
};

// Globe-specific colors
export const globeTheme = {
  background: bneColors.neutral[950],
  globe: {
    base: bneColors.primary[900],
    atmosphere: bneColors.primary[500],
    countries: bneColors.neutral[800],
    borders: bneColors.neutral[700],
  },
  regions: {
    'north_america': bneColors.primary[500],
    'latin_america': bneColors.secondary[500],
    'europe': bneColors.accent[500],
    'africa': bneColors.warning.main,
    'middle_east': bneColors.secondary[600],
    'asia': bneColors.info.main,
    'global': bneColors.neutral[400],
  },
  selected: {
    fill: bneColors.secondary[400],
    border: bneColors.secondary[300],
    glow: '0 0 30px rgba(245, 158, 11, 0.8)',
  },
  hover: {
    fill: bneColors.primary[400],
    border: bneColors.primary[300],
  },
};

// Complete theme object
export const bneTheme = {
  colors: bneColors,
  typography: bneTypography,
  spacing: bneSpacing,
  borderRadius: bneBorderRadius,
  shadows: bneShadows,
  gradients: bneGradients,
  animations: bneAnimations,
  breakpoints: bneBreakpoints,
  globe: globeTheme,
};

export type BNETheme = typeof bneTheme;

export default bneTheme;
