export const REGION_DEFINITIONS = [
  {
    id: 'NA',
    name: 'North America',
    center: { lat: 45, lon: -95 },
    radius: 0.55,
    scale: [1.7, 1.2],
    color: '#4EA8DE',
    gradient: 'from-bne-azure to-bne-emerald',
    metrics: {
      liquidityStress: 0.62,
      fundingSpread: 42,
      systemicPulse: 0.58
    },
    narrative:
      'US and Canadian wholesale markets stable; monitor cross-border USD funding channels for seasonal tightness.',
    countryNames: [
      'Canada',
      'United States of America',
      'Greenland',
      'Bermuda'
    ]
  },
  {
    id: 'LATAM',
    name: 'Latin America',
    center: { lat: -10, lon: -70 },
    radius: 0.48,
    scale: [1.6, 1.1],
    color: '#F59E0B',
    gradient: 'from-amber-400 to-bne-amber',
    metrics: {
      liquidityStress: 0.71,
      fundingSpread: 68,
      systemicPulse: 0.64
    },
    narrative:
      'FX-linked liquidity buffers remain under pressure. Mexico and Brazil interbank corridors require closer tracking.',
    countryNames: [
      'Belize',
      'Costa Rica',
      'Guatemala',
      'Honduras',
      'El Salvador',
      'Nicaragua',
      'Panama',
      'Cuba',
      'Jamaica',
      'Haiti',
      'Dominican Rep.',
      'Bahamas',
      'Barbados',
      'Saint Lucia',
      'Trinidad and Tobago',
      'Dominica',
      'Grenada',
      'St. Vin. and Gren.',
      'Antigua and Barb.',
      'St. Kitts and Nevis',
      'Colombia',
      'Venezuela',
      'Guyana',
      'Suriname',
      'Ecuador',
      'Peru',
      'Bolivia',
      'Brazil',
      'Paraguay',
      'Chile',
      'Argentina',
      'Uruguay'
    ]
  },
  {
    id: 'MENA',
    name: 'Middle East & North Africa',
    center: { lat: 23, lon: 35 },
    radius: 0.45,
    scale: [1.5, 1.1],
    color: '#F5B942',
    gradient: 'from-bne-steel to-bne-amber',
    metrics: {
      liquidityStress: 0.54,
      fundingSpread: 36,
      systemicPulse: 0.49
    },
    narrative:
      'Energy-linked sovereign flows stabilising Gulf interbank markets; monitor Egypt and Turkey for rollover risk.',
    countryNames: [
      'Morocco',
      'Algeria',
      'Tunisia',
      'Libya',
      'Egypt',
      'Sudan',
      'S. Sudan',
      'Mauritania',
      'W. Sahara',
      'Jordan',
      'Lebanon',
      'Israel',
      'Palestine',
      'Saudi Arabia',
      'United Arab Emirates',
      'Qatar',
      'Bahrain',
      'Kuwait',
      'Oman',
      'Yemen',
      'Iraq',
      'Syria',
      'Turkey',
      'Iran',
      'Cyprus'
    ]
  },
  {
    id: 'EU_WEST',
    name: 'Western Europe',
    center: { lat: 52, lon: 5 },
    radius: 0.5,
    scale: [1.8, 1.2],
    color: '#3ED2A1',
    gradient: 'from-bne-emerald to-bne-azure',
    metrics: {
      liquidityStress: 0.48,
      fundingSpread: 28,
      systemicPulse: 0.52
    },
    narrative:
      'Eurozone core banking network remains resilient; focus on collateral market depth as EUR funding demand rises.',
    countryNames: [
      'United Kingdom',
      'Ireland',
      'France',
      'Belgium',
      'Netherlands',
      'Luxembourg',
      'Germany',
      'Austria',
      'Switzerland',
      'Italy',
      'Spain',
      'Portugal',
      'Norway',
      'Sweden',
      'Finland',
      'Denmark',
      'Iceland',
      'Monaco',
      'Andorra',
      'San Marino',
      'Liechtenstein',
      'Malta'
    ]
  },
  {
    id: 'EU_EAST',
    name: 'Eastern Europe',
    center: { lat: 52, lon: 28 },
    radius: 0.46,
    scale: [1.6, 1.15],
    color: '#1F7CC1',
    gradient: 'from-bne-steel to-bne-azure',
    metrics: {
      liquidityStress: 0.63,
      fundingSpread: 53,
      systemicPulse: 0.61
    },
    narrative:
      'Monitor cross-border liquidity channels with EU core; heightened sensitivity to energy price swings persists.',
    countryNames: [
      'Poland',
      'Czechia',
      'Slovakia',
      'Hungary',
      'Romania',
      'Bulgaria',
      'Croatia',
      'Slovenia',
      'Serbia',
      'Bosnia and Herz.',
      'Montenegro',
      'Albania',
      'Macedonia',
      'Greece',
      'Estonia',
      'Latvia',
      'Lithuania',
      'Ukraine',
      'Belarus',
      'Moldova',
      'Georgia',
      'Armenia',
      'Azerbaijan',
      'Russia'
    ]
  },
  {
    id: 'PACIFIC',
    name: 'Pacific Rim',
    center: { lat: 8, lon: 140 },
    radius: 0.6,
    scale: [2.0, 1.1],
    color: '#5465FF',
    gradient: 'from-bne-azure to-indigo-400',
    metrics: {
      liquidityStress: 0.57,
      fundingSpread: 39,
      systemicPulse: 0.68
    },
    narrative:
      'Asia-Pacific interbank grid shows elevated systemic pulse driven by yen volatility and CNH offshore demand.',
    countryNames: [
      'China',
      'Japan',
      'South Korea',
      'North Korea',
      'India',
      'Pakistan',
      'Bangladesh',
      'Sri Lanka',
      'Thailand',
      'Vietnam',
      'Myanmar',
      'Laos',
      'Cambodia',
      'Malaysia',
      'Singapore',
      'Brunei',
      'Indonesia',
      'Philippines',
      'Australia',
      'New Zealand',
      'Papua New Guinea',
      'Fiji',
      'Solomon Is.',
      'Vanuatu',
      'Samoa',
      'Timor-Leste',
      'Mongolia',
      'Nepal',
      'Bhutan',
      'Hong Kong',
      'Taiwan'
    ]
  }
]

export const REGION_LOOKUP = REGION_DEFINITIONS.reduce((acc, region) => {
  acc[region.id] = region
  return acc
}, {})
