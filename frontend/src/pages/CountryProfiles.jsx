import { useState, useMemo } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useCountries, useCountrySync } from '../hooks/useCountries'
import { downloadCSV, downloadJSON, formatCountriesForExport } from '../utils/export'

function CountryCard({ country }) {
  const getRiskBadgeVariant = (level) => {
    const variants = {
      low: 'success',
      medium: 'default',
      high: 'warning',
      critical: 'danger'
    }
    return variants[level] || 'default'
  }

  const formatNumber = (num) => {
    if (!num) return 'N/A'
    return new Intl.NumberFormat('en-US', {
      notation: 'compact',
      compactDisplay: 'short',
      maximumFractionDigits: 1
    }).format(num)
  }

  const formatCurrency = (num) => {
    if (!num) return 'N/A'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      notation: 'compact',
      compactDisplay: 'short',
      maximumFractionDigits: 1
    }).format(num)
  }

  return (
    <Card className="hover:shadow-bne-hover transition-shadow cursor-pointer">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <CardTitle className="text-lg">{country.country_name}</CardTitle>
            <p className="text-xs text-bne-steel mt-0.5">{country.country_code} • {country.region}</p>
          </div>
          {country.risk_level && (
            <Badge variant={getRiskBadgeVariant(country.risk_level)} size="sm">
              {country.risk_level.toUpperCase()}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-bne-steel">GDP</span>
            <p className="font-semibold text-bne-ink mt-0.5">{formatCurrency(country.gdp_usd)}</p>
          </div>
          <div>
            <span className="text-bne-steel">Population</span>
            <p className="font-semibold text-bne-ink mt-0.5">{formatNumber(country.population)}</p>
          </div>
          <div>
            <span className="text-bne-steel">Banks</span>
            <p className="font-semibold text-bne-ink mt-0.5">{country.bank_count || 'N/A'}</p>
          </div>
          <div>
            <span className="text-bne-steel">Risk Score</span>
            <p className="font-semibold text-bne-ink mt-0.5">
              {country.risk_score ? `${parseFloat(country.risk_score).toFixed(1)}/100` : 'N/A'}
            </p>
          </div>
        </div>

        {(country.inflation_rate || country.unemployment_rate) && (
          <div className="mt-4 pt-4 border-t border-bne-frost">
            <div className="flex gap-4 text-xs">
              {country.inflation_rate && (
                <div className="flex-1">
                  <span className="text-bne-steel">Inflation</span>
                  <p className="font-medium text-bne-ink mt-0.5">
                    {parseFloat(country.inflation_rate).toFixed(1)}%
                  </p>
                </div>
              )}
              {country.unemployment_rate && (
                <div className="flex-1">
                  <span className="text-bne-steel">Unemployment</span>
                  <p className="font-medium text-bne-ink mt-0.5">
                    {parseFloat(country.unemployment_rate).toFixed(1)}%
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        <Button variant="outline" size="sm" className="w-full mt-4">
          View Details & Run Analysis
        </Button>
      </CardContent>
    </Card>
  )
}

function SearchFilters({ filters, onFiltersChange }) {
  const regions = ['North America', 'South America', 'Europe', 'Asia', 'Africa', 'Oceania', 'Middle East']
  const riskLevels = ['low', 'medium', 'high', 'critical']

  return (
    <Card>
      <CardHeader>
        <CardTitle>Filters</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <label className="text-sm font-medium text-bne-ink block mb-2">Search</label>
          <input
            type="text"
            placeholder="Search by name or code..."
            value={filters.search || ''}
            onChange={(e) => onFiltersChange({ ...filters, search: e.target.value })}
            className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
          />
        </div>

        <div>
          <label className="text-sm font-medium text-bne-ink block mb-2">Region</label>
          <select
            value={filters.region || ''}
            onChange={(e) => onFiltersChange({ ...filters, region: e.target.value || null })}
            className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
          >
            <option value="">All Regions</option>
            {regions.map(region => (
              <option key={region} value={region}>{region}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-sm font-medium text-bne-ink block mb-2">Risk Level</label>
          <select
            value={filters.risk_level || ''}
            onChange={(e) => onFiltersChange({ ...filters, risk_level: e.target.value || null })}
            className="w-full px-3 py-2 border border-bne-frost rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-bne-azure"
          >
            <option value="">All Levels</option>
            {riskLevels.map(level => (
              <option key={level} value={level}>{level.toUpperCase()}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-sm font-medium text-bne-ink block mb-2">
            <input
              type="checkbox"
              checked={filters.has_banking_data || false}
              onChange={(e) => onFiltersChange({ ...filters, has_banking_data: e.target.checked || null })}
              className="mr-2"
            />
            Only show countries with banking data
          </label>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => onFiltersChange({})}
          className="w-full"
        >
          Clear Filters
        </Button>
      </CardContent>
    </Card>
  )
}

export default function CountryProfiles() {
  const [filters, setFilters] = useState({})
  const [showExportMenu, setShowExportMenu] = useState(false)
  const { data: countriesData, isLoading, error, refetch } = useCountries(filters)
  const syncMutation = useCountrySync()

  const handleSync = () => {
    if (confirm('Sync country data from World Bank? This may take a few minutes.')) {
      syncMutation.mutate({
        start_year: 2018,
        end_year: 2023
      }, {
        onSuccess: () => {
          refetch()
          alert('Country data synced successfully!')
        },
        onError: (error) => {
          alert(`Sync failed: ${error.message}`)
        }
      })
    }
  }

  const handleExport = (format) => {
    if (!countriesData?.countries?.length) {
      alert('No data to export')
      return
    }

    const formattedData = formatCountriesForExport(countriesData.countries)
    const timestamp = new Date().toISOString().split('T')[0]
    const filename = `beacon-countries-${timestamp}`

    if (format === 'csv') {
      downloadCSV(formattedData, `${filename}.csv`)
    } else if (format === 'json') {
      downloadJSON(countriesData.countries, `${filename}.json`)
    }

    setShowExportMenu(false)
  }

  return (
    <PageContainer
      title="Country Profiles"
      subtitle="Pre-evaluate economic and financial metrics for countries before running ML models"
      actions={
        <div className="flex gap-2">
          <div className="relative">
            <Button
              variant="outline"
              onClick={() => setShowExportMenu(!showExportMenu)}
              disabled={!countriesData?.countries?.length}
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Export
              <svg className="w-4 h-4 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </Button>

            {showExportMenu && (
              <div className="absolute right-0 mt-2 w-48 rounded-lg bg-white shadow-bne-card border border-bne-frost py-2 z-10">
                <button
                  onClick={() => handleExport('csv')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-frost transition-colors flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Export as CSV
                </button>
                <button
                  onClick={() => handleExport('json')}
                  className="w-full text-left px-4 py-2 text-sm text-bne-ink hover:bg-bne-frost transition-colors flex items-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                  Export as JSON
                </button>
              </div>
            )}
          </div>

          <Button variant="outline" onClick={() => refetch()}>
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </Button>
          <Button
            variant="primary"
            onClick={handleSync}
            loading={syncMutation.isPending}
            disabled={syncMutation.isPending}
          >
            <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            Sync from World Bank
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1">
          <SearchFilters filters={filters} onFiltersChange={setFilters} />
        </div>

        <div className="lg:col-span-3">
          {isLoading ? (
            <Card>
              <CardContent className="py-12">
                <LoadingSpinner message="Loading countries..." />
              </CardContent>
            </Card>
          ) : error ? (
            <Card>
              <CardContent>
                <ErrorMessage error={error} />
              </CardContent>
            </Card>
          ) : countriesData?.countries?.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <svg className="w-16 h-16 mx-auto text-bne-steel/30 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <h3 className="text-lg font-semibold text-bne-ink mb-2">No Countries Found</h3>
                <p className="text-sm text-bne-steel mb-6">
                  {Object.keys(filters).length > 0
                    ? 'No countries match your filters. Try adjusting your search criteria.'
                    : 'No country data available yet. Click "Sync from World Bank" to import data.'}
                </p>
                <Button variant="primary" onClick={handleSync} loading={syncMutation.isPending}>
                  Sync from World Bank
                </Button>
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm text-bne-steel">
                  Found <span className="font-semibold text-bne-ink">{countriesData.total}</span> countries
                </p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {countriesData.countries.map((country) => (
                  <CountryCard key={country.id} country={country} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </PageContainer>
  )
}
