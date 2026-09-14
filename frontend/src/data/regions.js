export const regions = [
  {
    id: 'us-northeast',
    name: 'US Northeast',
    country: 'USA',
    iso3: 'USA',
    lat: 41.8781,
    lon: -87.6298,
    color: '#2C5545',
    bankCount: 1245
  },
  {
    id: 'us-southeast',
    name: 'US Southeast',
    country: 'USA',
    iso3: 'USA',
    lat: 33.7490,
    lon: -84.3880,
    color: '#2C5545',
    bankCount: 987
  },
  {
    id: 'us-midwest',
    name: 'US Midwest',
    country: 'USA',
    iso3: 'USA',
    lat: 41.8781,
    lon: -87.6298,
    color: '#2C5545',
    bankCount: 756
  },
  {
    id: 'us-southwest',
    name: 'US Southwest',
    country: 'USA',
    iso3: 'USA',
    lat: 29.7604,
    lon: -95.3698,
    color: '#2C5545',
    bankCount: 623
  },
  {
    id: 'us-west',
    name: 'US West',
    country: 'USA',
    iso3: 'USA',
    lat: 37.7749,
    lon: -122.4194,
    color: '#2C5545',
    bankCount: 892
  },
  {
    id: 'uk',
    name: 'United Kingdom',
    country: 'UK',
    iso3: 'GBR',
    lat: 51.5074,
    lon: -0.1278,
    color: '#55703B',
    bankCount: 342
  },
  {
    id: 'germany',
    name: 'Germany',
    country: 'Germany',
    iso3: 'DEU',
    lat: 52.5200,
    lon: 13.4050,
    color: '#55703B',
    bankCount: 428
  },
  {
    id: 'france',
    name: 'France',
    country: 'France',
    iso3: 'FRA',
    lat: 48.8566,
    lon: 2.3522,
    color: '#55703B',
    bankCount: 312
  },
  {
    id: 'italy',
    name: 'Italy',
    country: 'Italy',
    iso3: 'ITA',
    lat: 41.9028,
    lon: 12.4964,
    color: '#55703B',
    bankCount: 267
  },
  {
    id: 'spain',
    name: 'Spain',
    country: 'Spain',
    iso3: 'ESP',
    lat: 40.4168,
    lon: -3.7038,
    color: '#55703B',
    bankCount: 189
  },
  {
    id: 'japan',
    name: 'Japan',
    country: 'Japan',
    iso3: 'JPN',
    lat: 35.6762,
    lon: 139.6503,
    color: '#A87C1D',
    bankCount: 523
  },
  {
    id: 'china',
    name: 'China',
    country: 'China',
    iso3: 'CHN',
    lat: 39.9042,
    lon: 116.4074,
    color: '#A87C1D',
    bankCount: 678
  },
  {
    id: 'singapore',
    name: 'Singapore',
    country: 'Singapore',
    iso3: 'SGP',
    lat: 1.3521,
    lon: 103.8198,
    color: '#A87C1D',
    bankCount: 156
  },
  {
    id: 'australia',
    name: 'Australia',
    country: 'Australia',
    iso3: 'AUS',
    lat: -33.8688,
    lon: 151.2093,
    color: '#A33D22',
    bankCount: 234
  }
]

export function getRegionById(id) {
  return regions.find(r => r.id === id)
}

export function getRegionsByCountry(country) {
  return regions.filter(r => r.country === country)
}
