import { useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'

function MetricCard({ title, value, change, trend, icon }) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-2 bg-bne-azure/10 rounded-lg">
              {icon}
            </div>
          </div>
          <p className="text-sm text-bne-steel mb-1">{title}</p>
          <p className="text-2xl font-semibold text-bne-ink">{value}</p>
          {change && (
            <div className="flex items-center gap-1 mt-2">
              <Badge variant={trend === 'up' ? 'success' : 'danger'} size="sm">
                {trend === 'up' ? '↑' : '↓'} {change}
              </Badge>
              <span className="text-xs text-bne-steel">vs previous</span>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

function PredictionTable({ predictions }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-bne-frost">
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Step</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Predicted Value</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Actual Value</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Error</th>
            <th className="text-left py-3 px-4 text-sm font-semibold text-bne-ink">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {predictions.map((pred, i) => (
            <tr key={i} className="border-b border-bne-frost hover:bg-bne-ice transition-colors">
              <td className="py-3 px-4 text-sm text-bne-ink font-medium">Step {i + 1}</td>
              <td className="py-3 px-4 text-sm font-mono text-bne-ink">{pred.predicted.toFixed(4)}</td>
              <td className="py-3 px-4 text-sm font-mono text-bne-ink">
                {pred.actual ? pred.actual.toFixed(4) : '-'}
              </td>
              <td className="py-3 px-4 text-sm">
                {pred.actual ? (
                  <span className={`font-mono ${Math.abs(pred.error) > 0.1 ? 'text-bne-crimson' : 'text-bne-emerald'}`}>
                    {pred.error.toFixed(4)}
                  </span>
                ) : '-'}
              </td>
              <td className="py-3 px-4 text-sm">
                <Badge variant={pred.confidence > 0.8 ? 'success' : pred.confidence > 0.6 ? 'warning' : 'danger'} size="sm">
                  {(pred.confidence * 100).toFixed(1)}%
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SimpleChart({ data, label }) {
  const max = Math.max(...data.map(d => d.value))

  return (
    <div className="space-y-3">
      {data.map((item, i) => (
        <div key={i} className="space-y-1">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">{item.label}</span>
            <span className="font-medium text-bne-ink">{item.value.toFixed(4)}</span>
          </div>
          <div className="w-full h-2 bg-bne-frost rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-bne-azure to-bne-indigo transition-all duration-300"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Results() {
  const [selectedResult, setSelectedResult] = useState('recent')
  const [selectedRegion, setSelectedRegion] = useState('all')

  // Mock data - replace with actual API calls
  const mockPredictions = Array.from({ length: 4 }, (_, i) => ({
    predicted: 0.6234 + Math.random() * 0.2,
    actual: i < 2 ? 0.6534 + Math.random() * 0.15 : null,
    error: i < 2 ? (Math.random() - 0.5) * 0.1 : 0,
    confidence: 0.75 + Math.random() * 0.2
  }))

  const mockFeatureImportance = [
    { label: 'Total Assets', value: 0.2456 },
    { label: 'Net Income', value: 0.1823 },
    { label: 'Return on Assets', value: 0.1567 },
    { label: 'Tier 1 Capital Ratio', value: 0.1234 },
    { label: 'Non-Performing Loans', value: 0.0987 },
    { label: 'Cost-to-Income Ratio', value: 0.0756 },
    { label: 'Loan-to-Deposit Ratio', value: 0.0623 },
    { label: 'Liquidity Coverage', value: 0.0554 }
  ]

  const results = [
    { id: 'recent', label: 'Most Recent', date: '2024-11-03' },
    { id: 'best', label: 'Best Performance', date: '2024-10-28' },
    { id: 'previous', label: 'Previous Run', date: '2024-10-15' }
  ]

  return (
    <PageContainer
      title="Results"
      actions={
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export
            </span>
          </Button>
          <Button variant="primary" size="sm">
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Generate Report
            </span>
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          {results.map((result) => (
            <button
              key={result.id}
              onClick={() => setSelectedResult(result.id)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                selectedResult === result.id
                  ? 'bg-bne-azure text-white'
                  : 'bg-white text-bne-steel hover:bg-bne-frost'
              }`}
            >
              <div>{result.label}</div>
              <div className="text-xs opacity-75 mt-0.5">{result.date}</div>
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <MetricCard
            title="Average RMSE"
            value="0.0847"
            change="12.3%"
            trend="down"
            icon={
              <svg className="w-5 h-5 text-bne-azure" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            }
          />
          <MetricCard
            title="Model Accuracy"
            value="94.2%"
            change="2.1%"
            trend="up"
            icon={
              <svg className="w-5 h-5 text-bne-emerald" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            }
          />
          <MetricCard
            title="R² Score"
            value="0.8923"
            change="4.5%"
            trend="up"
            icon={
              <svg className="w-5 h-5 text-bne-indigo" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
              </svg>
            }
          />
          <MetricCard
            title="Predictions Made"
            value="1,247"
            icon={
              <svg className="w-5 h-5 text-bne-amber" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            }
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Predictions</CardTitle>
                  <div className="flex items-center gap-2">
                    <select className="px-3 py-1.5 text-sm border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure">
                      <option>All Regions</option>
                      <option>US Northeast</option>
                      <option>US Southeast</option>
                      <option>Europe</option>
                    </select>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <PredictionTable predictions={mockPredictions} />
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Feature Importance</CardTitle>
              </CardHeader>
              <CardContent>
                <SimpleChart data={mockFeatureImportance} label="Importance" />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Model Info</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div>
                    <p className="text-sm text-bne-steel mb-1">Model</p>
                    <p className="font-medium text-bne-ink">FDIC Multi-Scale LSTM</p>
                  </div>
                  <div>
                    <p className="text-sm text-bne-steel mb-1">Architecture</p>
                    <p className="font-medium text-bne-ink">LSTM (3 layers)</p>
                  </div>
                  <div>
                    <p className="text-sm text-bne-steel mb-1">Training Data</p>
                    <p className="font-medium text-bne-ink">2019-2024 (5 years)</p>
                  </div>
                  <div>
                    <p className="text-sm text-bne-steel mb-1">Last Updated</p>
                    <p className="font-medium text-bne-ink">2024-11-03</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Performance by Region</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { region: 'US Northeast', rmse: 0.0734, accuracy: 95.2 },
                { region: 'US Southeast', rmse: 0.0823, accuracy: 94.1 },
                { region: 'Europe', rmse: 0.0891, accuracy: 93.4 },
                { region: 'Asia Pacific', rmse: 0.0956, accuracy: 92.8 }
              ].map((data) => (
                <div key={data.region} className="p-4 bg-bne-ice rounded-lg">
                  <h4 className="font-medium text-bne-ink mb-3">{data.region}</h4>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-bne-steel">RMSE</span>
                      <span className="font-mono font-medium text-bne-ink">{data.rmse}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-bne-steel">Accuracy</span>
                      <Badge variant="success" size="sm">{data.accuracy}%</Badge>
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
