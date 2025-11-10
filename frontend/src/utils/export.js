function normalizeValue(value) {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : ''
  }
  if (value instanceof Date) {
    return value.toISOString()
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

function toCSVRow(headers, record) {
  return headers
    .map((header) => {
      const rawValue = normalizeValue(record[header])
      const stringValue = String(rawValue)
      if (stringValue.includes('"') || stringValue.includes(',') || stringValue.includes('\n')) {
        return `"${stringValue.replace(/"/g, '""')}"`
      }
      return stringValue
    })
    .join(',')
}

export function downloadCSV(rows, filename) {
  if (!Array.isArray(rows) || rows.length === 0) {
    console.warn('downloadCSV called without data to export')
    return
  }

  const headers = Object.keys(rows[0])
  const csvContent = [headers.join(','), ...rows.map((row) => toCSVRow(headers, row))].join('\n')

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function downloadJSON(data, filename) {
  if (!data) {
    console.warn('downloadJSON called without data to export')
    return
  }

  const jsonString = JSON.stringify(data, null, 2)
  const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function formatCountriesForExport(countries) {
  if (!Array.isArray(countries)) {
    return []
  }

  return countries.map((country) => ({
    Country: country.country_name ?? '',
    Code: country.country_code ?? '',
    Region: country.region ?? '',
    'Sub Region': country.sub_region ?? '',
    Capital: country.capital ?? '',
    Currency: country.currency ?? '',
    Population: country.population ?? '',
    'GDP (USD)': country.gdp_usd ?? '',
    'GDP Per Capita': country.gdp_per_capita ?? '',
    'GDP Growth Rate': country.gdp_growth_rate ?? '',
    'Inflation Rate': country.inflation_rate ?? '',
    'Unemployment Rate': country.unemployment_rate ?? '',
    'Credit to GDP': country.credit_to_gdp ?? '',
    'Debt to GDP': country.debt_to_gdp ?? '',
    'Fiscal Balance': country.fiscal_balance ?? '',
    'Current Account Balance': country.current_account_balance ?? '',
    'Bank Count': country.bank_count ?? '',
    'Total Bank Assets (USD)': country.total_bank_assets_usd ?? '',
    'Risk Level': country.risk_level ?? '',
    'Risk Score': country.risk_score ?? '',
    'Last Updated': country.last_updated ?? ''
  }))
}
