import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useDataSources } from '../hooks/useApi'

function DataSourceCard({ source }) {
  const statusVariants = {
    active: 'success',
    inactive: 'default',
    error: 'danger',
    syncing: 'primary'
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <CardTitle>{source.name || source.source_name}</CardTitle>
              <Badge variant={statusVariants[source.status] || 'default'} size="sm">
                {source.status || 'active'}
              </Badge>
            </div>
            <p className="text-sm text-bne-steel">{source.description}</p>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Source Type</span>
            <span className="font-medium text-bne-ink uppercase">{source.plugin_name || source.type}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Last Updated</span>
            <span className="font-medium text-bne-ink">
              {source.last_updated ? new Date(source.last_updated).toLocaleDateString() : 'Never'}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Records</span>
            <span className="font-medium text-bne-ink">{source.record_count?.toLocaleString() || '-'}</span>
          </div>
          {source.api_endpoint && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Endpoint</span>
              <span className="font-mono text-xs text-bne-ink truncate max-w-[200px]">
                {source.api_endpoint}
              </span>
            </div>
          )}
          {source.coverage && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Coverage</span>
              <span className="font-medium text-bne-ink">{source.coverage}</span>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button variant="primary" size="sm">
          Sync Now
        </Button>
        <Button variant="outline" size="sm">
          Configure
        </Button>
        <Button variant="ghost" size="sm">
          View Data
        </Button>
      </CardFooter>
    </Card>
  )
}

export default function DataSources() {
  const { data: sources, isLoading, error, refetch } = useDataSources()

  if (isLoading) {
    return (
      <PageContainer title="Data Sources">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading data sources..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Data Sources">
        <ErrorMessage
          title="Failed to load data sources"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  const activeSources = sources?.filter(s => s.status === 'active') || []
  const inactiveSources = sources?.filter(s => s.status !== 'active') || []

  return (
    <PageContainer
      title="Data Sources"
      actions={
        <Button variant="primary">
          <span className="flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Source
          </span>
        </Button>
      }
    >
      <div className="space-y-8">
        <Card className="bg-gradient-to-br from-bne-azure to-bne-indigo text-white">
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <p className="text-sm opacity-90 mb-2">Total Sources</p>
                <p className="text-3xl font-semibold">{sources?.length || 0}</p>
              </div>
              <div>
                <p className="text-sm opacity-90 mb-2">Active</p>
                <p className="text-3xl font-semibold">{activeSources.length}</p>
              </div>
              <div>
                <p className="text-sm opacity-90 mb-2">Last Sync</p>
                <p className="text-lg font-medium">2 hours ago</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {activeSources.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-bne-ink mb-4">Active Sources</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {activeSources.map((source) => (
                <DataSourceCard key={source.source_id || source.name} source={source} />
              ))}
            </div>
          </div>
        )}

        {inactiveSources.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-bne-ink mb-4">Inactive Sources</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {inactiveSources.map((source) => (
                <DataSourceCard key={source.source_id || source.name} source={source} />
              ))}
            </div>
          </div>
        )}

        {sources?.length === 0 && (
          <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
            <div className="text-center py-12">
              <svg
                className="w-16 h-16 mx-auto text-bne-steel/50 mb-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                />
              </svg>
              <h3 className="text-lg font-semibold text-bne-ink mb-2">No data sources configured</h3>
              <p className="text-sm text-bne-steel mb-4">
                Add your first data source to start collecting banking data
              </p>
              <Button variant="primary">
                Add Data Source
              </Button>
            </div>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Available Plugins</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                {
                  name: 'FDIC',
                  description: 'Federal Deposit Insurance Corporation',
                  icon: '🏦',
                  enabled: true
                },
                {
                  name: 'ECB Banking',
                  description: 'European Central Bank Data',
                  icon: '🇪🇺',
                  enabled: true
                },
                {
                  name: 'FMP',
                  description: 'Financial Modeling Prep',
                  icon: '📊',
                  enabled: true
                },
                {
                  name: 'Yahoo Finance',
                  description: 'Market data and financials',
                  icon: '📈',
                  enabled: false
                },
                {
                  name: 'World Bank',
                  description: 'Global economic indicators',
                  icon: '🌍',
                  enabled: false
                },
                {
                  name: 'IMF',
                  description: 'International Monetary Fund',
                  icon: '💰',
                  enabled: false
                }
              ].map((plugin) => (
                <div
                  key={plugin.name}
                  className={`p-4 rounded-lg border-2 ${
                    plugin.enabled
                      ? 'border-bne-azure/20 bg-bne-azure/5'
                      : 'border-bne-frost bg-white'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-2xl">{plugin.icon}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium text-bne-ink">{plugin.name}</h4>
                        {plugin.enabled && (
                          <Badge variant="success" size="sm">Enabled</Badge>
                        )}
                      </div>
                      <p className="text-xs text-bne-steel">{plugin.description}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}
