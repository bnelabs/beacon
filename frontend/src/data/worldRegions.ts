/**
 * Geographic region definitions with country mappings
 * ISO 3166-1 alpha-3 country codes
 */

export interface Region {
  id: string;
  name: string;
  displayName: string;
  color: string;
  countries: string[];
  center: [number, number]; // [longitude, latitude]
  zoomLevel: number;
}

export const REGIONS: Record<string, Region> = {
  north_america: {
    id: 'north_america',
    name: 'North America',
    displayName: 'North America',
    color: '#3B82F6',
    countries: ['USA', 'CAN', 'MEX'],
    center: [-100, 45],
    zoomLevel: 1.5,
  },
  latin_america: {
    id: 'latin_america',
    name: 'Latin America',
    displayName: 'Latin America',
    color: '#F59E0B',
    countries: [
      'BRA', 'ARG', 'CHL', 'COL', 'PER', 'VEN', 'ECU', 'BOL', 'PRY', 'URY',
      'GUY', 'SUR', 'GUF', // Guyana, Suriname, French Guiana
      'CRI', 'PAN', 'NIC', 'HND', 'SLV', 'GTM', 'BLZ', // Central America
      'CUB', 'DOM', 'HTI', 'JAM', 'TTO', 'BHS', 'BRB', // Caribbean
    ],
    center: [-60, -15],
    zoomLevel: 1.3,
  },
  europe: {
    id: 'europe',
    name: 'Europe',
    displayName: 'Europe',
    color: '#14B8A6',
    countries: [
      'GBR', 'FRA', 'DEU', 'ITA', 'ESP', 'POL', 'ROU', 'NLD', 'BEL', 'GRC',
      'CZE', 'PRT', 'SWE', 'HUN', 'AUT', 'BGR', 'DNK', 'FIN', 'SVK', 'IRL',
      'HRV', 'LTU', 'SVN', 'LVA', 'EST', 'CYP', 'LUX', 'MLT',
      'NOR', 'CHE', 'ISL', // Non-EU
      'UKR', 'BLR', 'MDA', 'RUS', // Eastern Europe
      'SRB', 'BIH', 'ALB', 'MKD', 'MNE', 'KOS', // Balkans
    ],
    center: [15, 50],
    zoomLevel: 1.8,
  },
  africa: {
    id: 'africa',
    name: 'Africa',
    displayName: 'Africa',
    color: '#D97706',
    countries: [
      'ZAF', 'NGA', 'EGY', 'KEN', 'ETH', 'GHA', 'TZA', 'UGA', 'DZA', 'MAR',
      'AGO', 'MOZ', 'MDG', 'CMR', 'CIV', 'NER', 'BFA', 'MLI', 'MWI', 'ZMB',
      'SOM', 'SEN', 'TCD', 'ZWE', 'GIN', 'RWA', 'BEN', 'TUN', 'BDI', 'SSD',
      'TGO', 'SLE', 'LBY', 'LBR', 'MRT', 'CAF', 'ERI', 'GMB', 'BWA', 'GAB',
      'NAM', 'LSO', 'GNQ', 'MUS', 'SWZ', 'DJI', 'COM', 'CPV', 'STP', 'SYC',
    ],
    center: [20, 0],
    zoomLevel: 1.3,
  },
  middle_east: {
    id: 'middle_east',
    name: 'Middle East',
    displayName: 'Middle East & North Africa',
    color: '#B45309',
    countries: [
      'SAU', 'ARE', 'QAT', 'KWT', 'OMN', 'BHR', 'YEM',
      'IRQ', 'IRN', 'SYR', 'JOR', 'LBN', 'ISR', 'PSE',
      'TUR', 'AFG', 'PAK',
    ],
    center: [45, 30],
    zoomLevel: 1.6,
  },
  asia: {
    id: 'asia',
    name: 'Asia',
    displayName: 'Asia & Pacific',
    color: '#2563EB',
    countries: [
      'CHN', 'JPN', 'IND', 'IDN', 'BGD', 'PHL', 'VNM', 'THA', 'MMR', 'KOR',
      'MYS', 'NPL', 'KHM', 'LKA', 'SGP', 'LAO', 'BTN', 'TLS', 'BRN', 'MDV',
      'MNG', 'KAZ', 'UZB', 'TKM', 'TJK', 'KGZ', 'ARM', 'GEO', 'AZE', // Central Asia
      'AUS', 'NZL', 'PNG', 'FJI', 'SLB', 'VUT', 'NCL', 'PLW', 'WSM', // Pacific
      'TWN', 'HKG', 'MAC', // Special regions
    ],
    center: [100, 30],
    zoomLevel: 1.3,
  },
  global: {
    id: 'global',
    name: 'Global',
    displayName: 'Global / Multi-Regional',
    color: '#64748B',
    countries: [], // All countries
    center: [0, 20],
    zoomLevel: 1,
  },
};

export const COUNTRY_TO_REGION: Record<string, string> = {};

// Build reverse mapping
Object.entries(REGIONS).forEach(([regionId, region]) => {
  region.countries.forEach(countryCode => {
    COUNTRY_TO_REGION[countryCode] = regionId;
  });
});

export const getRegionForCountry = (countryCode: string): string | null => {
  return COUNTRY_TO_REGION[countryCode] || null;
};

export const getRegion = (regionId: string): Region | null => {
  return REGIONS[regionId] || null;
};

export const getAllRegions = (): Region[] => {
  return Object.values(REGIONS);
};
