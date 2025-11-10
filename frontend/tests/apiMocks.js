const jobsList = [
  {
    id: 101,
    job_id: 101,
    job_type: 'data_collection',
    status: 'completed',
    model_id: 'Liquidity Forecaster',
    model_name: 'Liquidity Forecaster',
    created_at: '2024-02-01T10:00:00Z',
    started_at: '2024-02-01T10:05:00Z',
    completed_at: '2024-02-01T10:30:00Z',
    progress: 100,
    result: {
      records_collected: 1850,
      storage_path: '/var/beacon/jobs/101',
      per_source_metrics: {
        fdic: { completeness: 0.95, anomalies: 1 }
      }
    }
  },
  {
    id: 102,
    job_id: 102,
    job_type: 'training',
    status: 'running',
    model_id: 'Stress Tester',
    model_name: 'Stress Tester',
    created_at: '2024-02-10T08:00:00Z',
    started_at: '2024-02-10T08:05:00Z',
    progress: 68,
    result: {
      best_epoch: 9,
      final_train_loss: 0.0023,
      final_val_loss: 0.0031,
      test_rmse: 0.42,
      test_mae: 0.18,
      test_r2: 0.91,
      per_source_metrics: {
        fdic: { rmse: 0.41, mae: 0.19 },
        ecb: { rmse: 0.45, mae: 0.2 }
      },
      loss_history: {
        train: [0.85, 0.54, 0.32, 0.19, 0.12, 0.08],
        val: [0.9, 0.61, 0.4, 0.27, 0.2, 0.14]
      }
    }
  },
  {
    id: 103,
    job_id: 103,
    job_type: 'data_collection',
    status: 'failed',
    model_id: 'Liquidity Forecaster',
    model_name: 'Liquidity Forecaster',
    created_at: '2024-02-14T12:20:00Z',
    started_at: '2024-02-14T12:25:00Z',
    progress: 0,
    result: {
      error: 'Connection timeout while fetching data.'
    }
  }
]

const jobDetailsMap = Object.fromEntries(
  jobsList.map(job => [job.job_id, {
    ...job,
    parameters: {
      region: 'north_america',
      start_date: '2023-01-01',
      end_date: '2023-12-31'
    }
  }])
)

const jobQualityMap = {
  101: {
    quality_score: 0.82,
    completeness: 0.9,
    anomalies_detected: 2,
    anomalies_fixed: 2,
    fit_for_engine: true,
    warnings: ['Small gap detected in FDIC deposits series'],
    errors: []
  },
  103: {
    quality_score: 0.42,
    completeness: 0.55,
    anomalies_detected: 5,
    anomalies_fixed: 2,
    fit_for_engine: false,
    warnings: ['Missing values in ECB wholesale funding'],
    errors: ['Source connection failed before completion']
  }
}

const modelsList = [
  {
    id: 201,
    model_id: 201,
    name: 'Liquidity Forecaster',
    description: 'Predicts short-term liquidity stress for major banks.',
    status: 'ready',
    architecture: 'Temporal Attention',
    input_features: 18,
    prediction_steps: 5,
    accuracy: 0.92,
    last_trained: '2024-02-15T10:15:00Z',
    result: {
      test_r2: 0.92,
      test_rmse: 0.43,
      test_mae: 0.2,
      per_source_metrics: {
        fdic: { rmse: 0.43, mae: 0.21 },
        ecb: { rmse: 0.46, mae: 0.24 }
      }
    },
    metrics: {
      train_loss: [0.62, 0.41, 0.24, 0.12, 0.08],
      val_loss: [0.69, 0.48, 0.29, 0.19, 0.13],
      best_epoch: 8
    },
    data_summary: {
      rows: 14200,
      features: 35,
      lookback_days: 365
    }
  },
  {
    id: 202,
    model_id: 202,
    name: 'Stress Tester',
    description: 'Scenario-driven liquidity risk projections.',
    status: 'training',
    architecture: 'Graph Temporal Network',
    input_features: 24,
    prediction_steps: 8,
    accuracy: 0.0,
    last_trained: '2024-02-12T09:00:00Z',
    result: {
      test_r2: 0.86,
      test_rmse: 0.51,
      test_mae: 0.27
    },
    metrics: {
      train_loss: [0.9, 0.63, 0.44, 0.32],
      val_loss: [0.95, 0.68, 0.47, 0.34]
    },
    data_summary: {
      rows: 11800,
      features: 42,
      lookback_days: 540
    }
  },
  {
    id: 203,
    model_id: 203,
    name: 'Capital Adequacy Draft',
    description: 'Draft model for Basel III capital scenarios.',
    status: 'draft',
    architecture: 'LSTM',
    input_features: 12,
    prediction_steps: 4,
    accuracy: 0.0,
    last_trained: null,
    result: {},
    metrics: {
      train_loss: [],
      val_loss: []
    },
    data_summary: {
      rows: 6400,
      features: 18,
      lookback_days: 270
    }
  }
]

const modelDetailMap = Object.fromEntries(
  modelsList.map(model => [model.model_id, {
    ...model,
    scenarios: [
      {
        scenario_id: 301,
        name: 'Baseline Stress',
        horizon_days: 30,
        created_at: '2024-02-05T11:00:00Z',
        adjustments: [
          { source: 'FDIC Deposits', type: 'pct', value: -7.5 },
          { source: 'Wholesale Funding', type: 'pct', value: -12 }
        ],
        summary: {
          num_series: 6,
          avg_risk_score: 0.38,
          max_risk_score: 0.52,
          min_risk_score: 0.21,
          recovery_days: 9
        },
        predictions: [
          {
            source: 'Liquidity Buffer',
            key: 'liquidity-buffer',
            label: 'Liquidity Buffer',
            prediction: 0.87,
            risk_score: 0.42,
            confidence: { lower: 0.74, upper: 0.95 },
            explanation: 'Buffer dips under stress but recovers within 10 days.'
          },
          {
            source: 'Cash Burn Rate',
            key: 'cash-burn',
            label: 'Cash Burn Rate',
            prediction: 0.21,
            risk_score: 0.36,
            confidence: { lower: 0.18, upper: 0.28 },
            explanation: 'Slight acceleration driven by wholesale funding shock.'
          }
        ]
      }
    ]
  }])
)

const scenarioDetailMap = {
  '201:301': modelDetailMap[201].scenarios[0],
  '201:999': {
    scenario_id: 999,
    model_id: 201,
    name: 'Custom Scenario',
    horizon_days: 30,
    created_at: '2024-03-01T12:00:00Z',
    adjustments: [
      { source: 'fdic', type: 'pct', value: 5 },
      { source: 'ecb', type: 'pct', value: -10 }
    ],
    summary: {
      avg_risk_score: 0.33,
      max_risk_score: 0.45,
      min_risk_score: 0.21,
      num_series: 1
    },
    predictions: [
      {
        source: 'fdic',
        key: 'custom-series',
        label: 'Custom Series',
        prediction: 0.74,
        risk_score: 0.33,
        confidence: { lower: 0.61, upper: 0.82 },
        explanation: 'Scenario executed with mocked response.'
      }
    ]
  }
}

const dataSourcesList = [
  {
    id: 401,
    name: 'FDIC Call Reports',
    description: 'Quarterly balance sheet metrics for US banks.',
    plugin_type: 'fdic',
    status: 'active',
    enabled: true,
    record_count: 128_000,
    last_successful_fetch: '2024-02-14T17:30:00Z',
    api_endpoint: 'https://api.fdic.gov/bank/find',
    coverage_description: 'US Depository Institutions'
  },
  {
    id: 402,
    name: 'ECB Banking',
    description: 'European Central Bank supervisory statistics.',
    plugin_type: 'ecb_banking',
    status: 'active',
    enabled: true,
    record_count: 54_000,
    last_successful_fetch: '2024-02-12T13:00:00Z',
    api_endpoint: 'https://data.ecb.europa.eu',
    coverage_description: 'Eurozone banks'
  },
  {
    id: 403,
    name: 'World Bank Finance',
    description: 'Macro-financial indicators from the World Bank.',
    plugin_type: 'world_bank',
    status: 'inactive',
    enabled: false,
    record_count: 0,
    last_successful_fetch: null,
    api_endpoint: 'https://api.worldbank.org',
    coverage_description: 'Global'
  }
]

const catalogueItems = [
  {
    id: 501,
    code: 'FDIC_LIQUIDITY',
    name: 'FDIC Liquidity Coverage',
    category: 'Liquidity',
    region: 'North America',
    description: 'Liquidity coverage ratios for US banks.',
    parameters: { risk_score: 0.78 },
    data_source: { name: 'FDIC Call Reports' }
  },
  {
    id: 502,
    code: 'ECB_TIER1',
    name: 'ECB Tier 1 Capital',
    category: 'Capital',
    region: 'Europe',
    description: 'Tier 1 capital ratios for Eurozone banks.',
    parameters: { risk_score: 0.72 },
    data_source: { name: 'ECB Banking' }
  },
  {
    id: 503,
    code: 'WB_GDP',
    name: 'Global GDP Growth',
    category: 'Macro',
    region: 'Global',
    description: 'Annual GDP growth rates.',
    parameters: { risk_score: 0.55 },
    data_source: { name: 'World Bank Finance' }
  }
]

const countriesResponse = {
  total: 3,
  countries: [
    {
      id: 601,
      country_name: 'United States',
      country_code: 'USA',
      region: 'North America',
      risk_level: 'medium',
      gdp_usd: 23_300_000_000_000,
      population: 331_000_000,
      bank_count: 4800,
      risk_score: 72,
      inflation_rate: 3.4,
      unemployment_rate: 4.1
    },
    {
      id: 602,
      country_name: 'Germany',
      country_code: 'DEU',
      region: 'Europe',
      risk_level: 'low',
      gdp_usd: 4_200_000_000_000,
      population: 83_000_000,
      bank_count: 1400,
      risk_score: 58,
      inflation_rate: 2.6,
      unemployment_rate: 3.3
    },
    {
      id: 603,
      country_name: 'Brazil',
      country_code: 'BRA',
      region: 'South America',
      risk_level: 'high',
      gdp_usd: 1_800_000_000_000,
      population: 212_000_000,
      bank_count: 600,
      risk_score: 81,
      inflation_rate: 5.9,
      unemployment_rate: 8.4
    }
  ]
}

const countryIndicators = {
  GDP: [
    { year: 2019, value: 2.3 },
    { year: 2020, value: -3.4 },
    { year: 2021, value: 5.7 },
    { year: 2022, value: 2.1 }
  ]
}

const countryRegions = {
  regions: [
    { id: 'north_america', name: 'North America', country_count: 2 },
    { id: 'europe', name: 'Europe', country_count: 3 },
    { id: 'asia', name: 'Asia', country_count: 4 }
  ]
}

const countryRiskSummary = {
  totals: {
    low: 18,
    medium: 9,
    high: 4,
    critical: 1
  }
}

const analyticsOverview = {
  jobs: {
    total: 128,
    completed: 112,
    failed: 6,
    success_rate: 91,
    avg_execution_time: 238,
    distribution: {
      data_collection: 58,
      training: 42,
      inference: 28
    }
  },
  models: {
    total: 6,
    ready: 4,
    health_percentage: 88
  },
  data_quality: {
    avg_quality_score: 0.82,
    avg_completeness: 0.9,
    jobs_analyzed: 42
  }
}

const analyticsTrends = {
  series: Array.from({ length: 20 }).map((_, index) => ({
    date: new Date(Date.UTC(2024, 0, index + 1)).toISOString(),
    value: 0.65 + index * 0.01
  }))
}

const analyticsAnomalies = {
  anomalies_detected: 2,
  anomalies: [
    {
      severity: 'high',
      type: 'job_failure',
      message: 'Training job 102 exceeded retry limit due to convergence issues.',
      detected_at: '2024-02-19T11:45:00Z'
    },
    {
      severity: 'medium',
      type: 'data_quality',
      message: 'Data completeness dropped 10% for ECB Banking source.',
      detected_at: '2024-02-18T09:20:00Z'
    }
  ]
}

const dataQualityStats = {
  overview: {
    overall_health: 84,
    active_sources: 8,
    total_sources: 10,
    active_issues: 3
  },
  freshness: {
    fresh: 6,
    stale: 2,
    outdated: 1,
    never_synced: 1,
    freshness_percentage: 75
  },
  quality: {
    avg_quality_score: 0.76,
    avg_completeness: 92,
    jobs_analyzed: 26
  },
  anomalies: {
    low_quality_jobs: 1,
    error_sources: 1,
    recent_failures: 1,
    stale_sources: 2
  }
}

const dataQualitySources = [
  {
    id: 401,
    name: 'FDIC Call Reports',
    plugin_type: 'fdic',
    status: 'active',
    enabled: true,
    freshness_status: 'fresh',
    days_since_update: 2,
    avg_quality_score: 0.88,
    last_fetch: '2024-02-14T17:30:00Z'
  },
  {
    id: 402,
    name: 'ECB Banking',
    plugin_type: 'ecb_banking',
    status: 'active',
    enabled: true,
    freshness_status: 'stale',
    days_since_update: 9,
    avg_quality_score: 0.71,
    last_fetch: '2024-02-07T13:00:00Z'
  },
  {
    id: 403,
    name: 'World Bank Finance',
    plugin_type: 'world_bank',
    status: 'inactive',
    enabled: false,
    freshness_status: 'never_synced',
    days_since_update: null,
    avg_quality_score: null,
    last_fetch: null
  }
]

const dataQualityTrends = Array.from({ length: 14 }).map((_, index) => ({
  date: new Date(Date.UTC(2024, 1, index + 1)).toISOString().split('T')[0],
  avg_quality_score: 0.6 + index * 0.015
}))

const bankCatalogue = catalogueItems.map(item => ({
  id: item.id,
  code: item.code,
  name: item.name,
  category: item.category,
  region: item.region,
  description: item.description,
  metadata: { risk_score: item.parameters?.risk_score ?? 0.6 },
  data_source: { name: item.data_source?.name || 'Catalogue' }
}))

function jsonResponse(route, payload, status = 200) {
  return route.fulfill({
    status,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function registerApiMocks(page) {
  await page.addInitScript(() => {
    class MockWebSocket {
      constructor() {
        this.readyState = 1
        setTimeout(() => {
          this.onopen?.({})
        }, 10)
      }
      send() {}
      close() {
        this.readyState = 3
        this.onclose?.({})
      }
      addEventListener(event, handler) {
        this[`on${event}`] = handler
      }
    }
    window.WebSocket = MockWebSocket
  })

  page.on('dialog', async (dialog) => {
    try {
      await dialog.accept()
    } catch (error) {
      console.error('Failed to handle dialog', error)
    }
  })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const normalizedPath = path.endsWith('/') && path !== '/api' ? path.slice(0, -1) : path

    const respond = (payload, status = 200) => jsonResponse(route, payload, status)

    if (method === 'GET') {
      if (normalizedPath === '/api/v1/jobs') {
        if (path.endsWith('/')) {
          return respond({ jobs: jobsList })
        }
        return respond(jobsList)
      }

      const jobDetailMatch = normalizedPath.match(/\/api\/v1\/jobs\/(\d+)$/)
      if (jobDetailMatch) {
        const jobId = Number(jobDetailMatch[1])
        const detail = jobDetailsMap[jobId]
        return respond(detail ?? { job_id: jobId, status: 'unknown' })
      }

      const jobQualityMatch = normalizedPath.match(/\/api\/v1\/results\/(\d+)\/data-quality$/)
      if (jobQualityMatch) {
        const jobId = Number(jobQualityMatch[1])
        return respond(jobQualityMap[jobId] ?? {})
      }

      if (normalizedPath === '/api/models') {
        return respond(modelsList)
      }

      const modelDetailMatch = normalizedPath.match(/\/api\/models\/(\d+)$/)
      if (modelDetailMatch) {
        const modelId = Number(modelDetailMatch[1])
        return respond(modelDetailMap[modelId] ?? { model_id: modelId, name: 'Unknown Model' })
      }

      const scenarioMatch = normalizedPath.match(/\/api\/models\/(\d+)\/scenarios\/(\d+)$/)
      if (scenarioMatch) {
        const key = `${scenarioMatch[1]}:${scenarioMatch[2]}`
        return respond(scenarioDetailMap[key] ?? null)
      }

      if (normalizedPath === '/api/v1/data-sources') {
        return respond(dataSourcesList)
      }

      if (normalizedPath === '/api/v1/catalogue') {
        return respond(bankCatalogue)
      }

      if (normalizedPath === '/api/v1/data-catalogue') {
        return respond({ items: catalogueItems })
      }

      if (normalizedPath === '/api/v1/countries') {
        return respond(countriesResponse)
      }

      if (normalizedPath === '/api/v1/countries/regions/list') {
        return respond(countryRegions)
      }

      if (normalizedPath === '/api/v1/countries/risk-levels/summary') {
        return respond(countryRiskSummary)
      }

      const countryDetailMatch = normalizedPath.match(/\/api\/v1\/countries\/([A-Z]{3})$/)
      if (countryDetailMatch) {
        const code = countryDetailMatch[1]
        const country = countriesResponse.countries.find((item) => item.country_code === code)
        return respond(country ?? null)
      }

      const indicatorMatch = normalizedPath.match(/\/api\/v1\/countries\/([A-Z]{3})\/indicators$/)
      if (indicatorMatch) {
        return respond(countryIndicators)
      }

      if (normalizedPath === '/api/v1/analytics/overview') {
        return respond(analyticsOverview)
      }

      if (normalizedPath === '/api/v1/analytics/trends/time-series') {
        return respond(analyticsTrends)
      }

      if (normalizedPath === '/api/v1/analytics/insights/anomalies') {
        return respond(analyticsAnomalies)
      }

      if (normalizedPath === '/api/v1/data-quality/stats') {
        return respond(dataQualityStats)
      }

      if (normalizedPath === '/api/v1/data-quality/sources') {
        return respond(dataQualitySources)
      }

      if (normalizedPath === '/api/v1/data-quality/trends') {
        return respond({ trends: dataQualityTrends })
      }

      const banksByRegionMatch = normalizedPath === '/api/v1/catalogue'
      if (banksByRegionMatch) {
        return respond(bankCatalogue)
      }

      // Default GET response
      return respond({})
    }

    if (method === 'POST') {
      if (normalizedPath === '/api/v1/jobs') {
        const newJobId = jobsList.length + 100
        return respond({ job_id: newJobId, status: 'queued' }, 201)
      }

      const cancelMatch = normalizedPath.match(/\/api\/v1\/jobs\/(\d+)\/cancel$/)
      if (cancelMatch) {
        const jobId = Number(cancelMatch[1])
        return respond({ job_id: jobId, status: 'cancelled' })
      }

      if (normalizedPath === '/api/v1/jobs/batch/cancel') {
        return respond({ cancelled: jobsList.map(job => job.job_id), failed: [] })
      }

      if (normalizedPath === '/api/v1/data-sources') {
        return respond({ id: 450, status: 'created' }, 201)
      }

      const syncMatch = normalizedPath.match(/\/api\/v1\/data-sources\/(\d+)\/sync$/)
      if (syncMatch) {
        const sourceId = Number(syncMatch[1])
        return respond({ id: sourceId, status: 'syncing' })
      }

      if (normalizedPath === '/api/v1/countries/sync') {
        return respond({ status: 'started' })
      }

      if (normalizedPath === '/api/v1/countries/compare') {
        return respond({ comparison: [] })
      }

      const simulateMatch = normalizedPath.match(/\/api\/models\/(\d+)\/simulate$/)
      if (simulateMatch) {
        const modelId = Number(simulateMatch[1])
        return respond({
          scenario_id: 999,
          model_id: modelId,
          name: 'Custom Scenario',
          horizon_days: 30,
          summary: {
            avg_risk_score: 0.33,
            max_risk_score: 0.45,
            min_risk_score: 0.21,
            num_series: 1
          },
          adjustments: [
            { source: 'fdic', type: 'pct', value: 5 },
            { source: 'ecb', type: 'pct', value: -10 }
          ],
          predictions: [
            {
              source: 'fdic',
              key: 'custom-series',
              label: 'Custom Series',
              prediction: 0.74,
              risk_score: 0.33,
              confidence: { lower: 0.61, upper: 0.82 },
              explanation: 'Scenario executed with mocked response.'
            }
          ]
        })
      }

      // Default POST success
      return respond({ ok: true })
    }

    if (method === 'PUT') {
      const updateSourceMatch = normalizedPath.match(/\/api\/v1\/data-sources\/(\d+)$/)
      if (updateSourceMatch) {
        const sourceId = Number(updateSourceMatch[1])
        return respond({ id: sourceId, status: 'updated' })
      }

      return respond({ ok: true })
    }

    // Other HTTP methods
    return respond({ ok: true })
  })
}
