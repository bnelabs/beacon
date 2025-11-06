/**
 * Interbank network connections data
 *
 * Each connection represents interbank exposure between regions.
 * This data structure will be replaced with real-time API data in production.
 *
 * Risk levels: low (0-0.3), medium (0.3-0.6), high (0.6-0.8), critical (0.8-1.0)
 */

export const networkConnections = [
  // US Internal Network
  {
    id: 'conn-1',
    source: 'us-northeast',
    target: 'us-midwest',
    exposure: 125000000000, // $125B
    riskScore: 0.25,
    transactionVolume: 45000
  },
  {
    id: 'conn-2',
    source: 'us-northeast',
    target: 'us-southeast',
    exposure: 98000000000,
    riskScore: 0.18,
    transactionVolume: 38000
  },
  {
    id: 'conn-3',
    source: 'us-west',
    target: 'us-southwest',
    exposure: 87000000000,
    riskScore: 0.22,
    transactionVolume: 32000
  },
  {
    id: 'conn-4',
    source: 'us-west',
    target: 'us-northeast',
    exposure: 156000000000,
    riskScore: 0.31,
    transactionVolume: 52000
  },

  // Trans-Atlantic Connections
  {
    id: 'conn-5',
    source: 'us-northeast',
    target: 'uk',
    exposure: 234000000000, // $234B
    riskScore: 0.42,
    transactionVolume: 78000
  },
  {
    id: 'conn-6',
    source: 'us-northeast',
    target: 'germany',
    exposure: 187000000000,
    riskScore: 0.38,
    transactionVolume: 64000
  },
  {
    id: 'conn-7',
    source: 'us-northeast',
    target: 'france',
    exposure: 145000000000,
    riskScore: 0.35,
    transactionVolume: 51000
  },

  // European Network
  {
    id: 'conn-8',
    source: 'uk',
    target: 'germany',
    exposure: 276000000000,
    riskScore: 0.28,
    transactionVolume: 92000
  },
  {
    id: 'conn-9',
    source: 'germany',
    target: 'france',
    exposure: 198000000000,
    riskScore: 0.24,
    transactionVolume: 71000
  },
  {
    id: 'conn-10',
    source: 'france',
    target: 'italy',
    exposure: 134000000000,
    riskScore: 0.56,
    transactionVolume: 48000
  },
  {
    id: 'conn-11',
    source: 'germany',
    target: 'italy',
    exposure: 112000000000,
    riskScore: 0.62,
    transactionVolume: 39000
  },
  {
    id: 'conn-12',
    source: 'spain',
    target: 'france',
    exposure: 89000000000,
    riskScore: 0.47,
    transactionVolume: 31000
  },

  // Trans-Pacific Connections
  {
    id: 'conn-13',
    source: 'us-west',
    target: 'japan',
    exposure: 203000000000,
    riskScore: 0.33,
    transactionVolume: 69000
  },
  {
    id: 'conn-14',
    source: 'us-west',
    target: 'singapore',
    exposure: 145000000000,
    riskScore: 0.29,
    transactionVolume: 52000
  },
  {
    id: 'conn-15',
    source: 'us-west',
    target: 'china',
    exposure: 312000000000,
    riskScore: 0.58,
    transactionVolume: 95000
  },

  // Asian Network
  {
    id: 'conn-16',
    source: 'japan',
    target: 'singapore',
    exposure: 167000000000,
    riskScore: 0.26,
    transactionVolume: 58000
  },
  {
    id: 'conn-17',
    source: 'singapore',
    target: 'china',
    exposure: 189000000000,
    riskScore: 0.41,
    transactionVolume: 67000
  },
  {
    id: 'conn-18',
    source: 'japan',
    target: 'china',
    exposure: 245000000000,
    riskScore: 0.49,
    transactionVolume: 82000
  },
  {
    id: 'conn-19',
    source: 'singapore',
    target: 'australia',
    exposure: 78000000000,
    riskScore: 0.21,
    transactionVolume: 28000
  },

  // Europe-Asia Connections
  {
    id: 'conn-20',
    source: 'uk',
    target: 'singapore',
    exposure: 134000000000,
    riskScore: 0.36,
    transactionVolume: 47000
  },
  {
    id: 'conn-21',
    source: 'germany',
    target: 'china',
    exposure: 178000000000,
    riskScore: 0.52,
    transactionVolume: 61000
  },

  // High Risk Connections (for demo purposes)
  {
    id: 'conn-22',
    source: 'italy',
    target: 'spain',
    exposure: 67000000000,
    riskScore: 0.73, // High risk
    transactionVolume: 23000
  },
  {
    id: 'conn-23',
    source: 'us-southeast',
    target: 'us-midwest',
    exposure: 92000000000,
    riskScore: 0.85, // Critical risk
    transactionVolume: 34000
  }
]

/**
 * Get connections for a specific region
 */
export function getConnectionsForRegion(regionId) {
  return networkConnections.filter(
    conn => conn.source === regionId || conn.target === regionId
  )
}

/**
 * Get risk color based on risk score
 */
export function getRiskColor(riskScore) {
  if (riskScore < 0.3) return '#10B981' // green (low risk)
  if (riskScore < 0.6) return '#F59E0B' // amber (medium risk)
  if (riskScore < 0.8) return '#EF4444' // red (high risk)
  return '#DC2626' // dark red (critical risk)
}

/**
 * Get risk level label
 */
export function getRiskLevel(riskScore) {
  if (riskScore < 0.3) return 'Low'
  if (riskScore < 0.6) return 'Medium'
  if (riskScore < 0.8) return 'High'
  return 'Critical'
}

/**
 * Format exposure amount
 */
export function formatExposure(amount) {
  if (amount >= 1e9) {
    return `$${(amount / 1e9).toFixed(1)}B`
  }
  if (amount >= 1e6) {
    return `$${(amount / 1e6).toFixed(1)}M`
  }
  return `$${amount.toLocaleString()}`
}
