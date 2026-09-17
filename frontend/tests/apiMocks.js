// Job rows in the exact shape GET /api/v1/jobs answers with (JobResponse:
// id, celery_task_id, job_type, status, progress, result, error_message,
// user_friendly_error, created_at, started_at, completed_at,
// peak_memory_mb, execution_time_seconds + JobBase's parameters).
//
// Deliberately absent, because no transport sends them: `job_id` (only the
// WebSocket job_update payload adds it, alongside `id`), `name`, `model_id`,
// `config`, `logs`. Earlier fixtures carried all five; the UI grew reads for
// them, and production rendered "Unknown Model" and empty cards while the
// suite stayed green. The mock answers as the real API does -- including in
// what it does NOT say.
const jobsList = [
  {
    id: 101,
    celery_task_id: null,
    job_type: 'data_collection',
    status: 'completed',
    progress: 100,
    parameters: {
      regions: ['north_america'],
      start_date: '2023-01-01',
      end_date: '2023-12-31'
    },
    result: {
      records_collected: 1850,
      storage_path: '/var/beacon/jobs/101',
      per_source_metrics: {
        fdic: { completeness: 0.95, anomalies: 1 }
      }
    },
    error_message: null,
    user_friendly_error: null,
    created_at: '2024-02-01T10:00:00Z',
    started_at: '2024-02-01T10:05:00Z',
    completed_at: '2024-02-01T10:30:00Z',
    peak_memory_mb: null,
    execution_time_seconds: 1500
  },
  {
    id: 102,
    celery_task_id: null,
    job_type: 'training',
    status: 'running',
    progress: 68,
    parameters: {
      data_job_id: 101,
      train_start: '2023-01-01',
      train_end: '2023-09-30',
      test_start: '2023-10-01',
      test_end: '2023-12-31',
      config: {
        model: 'temporal_attention',
        epochs: 25,
        sequence_length: 30,
        batch_size: 32,
        learning_rate: 0.001,
        dropout: 0.1
      }
    },
    // A running training job streams partial metrics (the WS payload carries
    // `result`); loss histories are the flat keys job_tasks.py writes.
    result: {
      model_type: 'temporal_attention',
      model_version: '1.0.0',
      best_epoch: 9,
      final_train_loss: 0.0023,
      final_val_loss: 0.0031,
      test_rmse: 0.42,
      test_mae: 0.18,
      test_r2: 0.91,
      train_loss_history: [0.85, 0.54, 0.32, 0.19, 0.12, 0.08],
      val_loss_history: [0.9, 0.61, 0.4, 0.27, 0.2, 0.14],
      per_source_metrics: {
        fdic: { rmse: 0.41, mae: 0.19 },
        ecb: { rmse: 0.45, mae: 0.2 }
      }
    },
    error_message: null,
    user_friendly_error: null,
    created_at: '2024-02-10T08:00:00Z',
    started_at: '2024-02-10T08:05:00Z',
    completed_at: null,
    peak_memory_mb: null,
    execution_time_seconds: null
  },
  {
    id: 103,
    celery_task_id: null,
    job_type: 'data_collection',
    status: 'failed',
    progress: 0,
    parameters: { regions: ['europe'] },
    result: null,
    error_message: 'Connection timeout while fetching data.',
    user_friendly_error:
      'The provider stopped answering mid-download. Nothing was written; retrying is safe.',
    created_at: '2024-02-14T12:20:00Z',
    started_at: '2024-02-14T12:25:00Z',
    completed_at: null,
    peak_memory_mb: null,
    execution_time_seconds: null
  },
  {
    // The backtest job the predictive-validity report is served for:
    // GET /api/v2/reports/validation/{id} answers `validated` only for
    // backtest jobs whose result carries event_metrics.
    id: 104,
    celery_task_id: null,
    job_type: 'backtest',
    status: 'completed',
    progress: 100,
    parameters: { trained_model_job: 102, event_definition: { direction: 'down', quantile: 0.95, horizon: 5, min_duration: 2 } },
    result: {
      backtest_metrics: {
        event_metrics: {
          definition: { direction: 'down', quantile: 0.95, horizon: 5, min_duration: 2 },
          by_source: {
            fdic: {
              roc_auc: 0.78,
              average_precision: 0.64,
              n_events: 9,
              lead_time: { median_lead: 3, n_zero_lead: 1 }
            },
            ecb: { skipped: 'insufficient stress events in window' }
          }
        },
        mse: 0.19,
        mae: 0.31,
        rmse: 0.44,
        r2: 0.83
      }
    },
    error_message: null,
    user_friendly_error: null,
    created_at: '2024-02-16T09:00:00Z',
    started_at: '2024-02-16T09:02:00Z',
    completed_at: '2024-02-16T09:40:00Z',
    peak_memory_mb: null,
    execution_time_seconds: 2280
  }
]

// GET /api/v1/jobs/{id} answers the same JobResponse shape as the list.
const jobDetailsMap = Object.fromEntries(jobsList.map(job => [job.id, job]))

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

// Model rows in the exact shape GET /api/models answers with (ModelSummary):
// model_id, name, created_at, status, model_type, model_version, metrics
// {mae, rmse, r2, accuracy, best_val_loss}, tags, data_job_id,
// predictions_available. The list is completed training jobs, and `name` is
// the training result's model_type upper-cased -- that is what the route
// builds, so that is what the fixture says. Earlier fixtures carried
// description/architecture/input_features/prediction_steps/accuracy/
// last_trained/data_summary: fields no endpoint sends, which the UI filled
// with invented defaults ("LSTM", 12, 4).
const modelsList = [
  {
    model_id: 201,
    name: 'TEMPORAL_ATTENTION',
    created_at: '2024-02-15T10:15:00Z',
    status: 'completed',
    model_type: 'temporal_attention',
    model_version: '1.0.0',
    metrics: { mae: 0.2, rmse: 0.43, r2: 0.92, accuracy: null, best_val_loss: 0.13 },
    tags: ['multi-source'],
    data_job_id: 101,
    predictions_available: true
  },
  {
    model_id: 202,
    name: 'HGT',
    created_at: '2024-02-12T09:00:00Z',
    status: 'completed',
    model_type: 'hgt',
    model_version: '0.9.0',
    metrics: { mae: 0.27, rmse: 0.51, r2: 0.86, accuracy: null, best_val_loss: 0.34 },
    tags: [],
    data_job_id: 101,
    predictions_available: false
  },
  {
    model_id: 203,
    name: 'LSTM',
    created_at: '2024-02-08T09:00:00Z',
    status: 'completed',
    model_type: 'lstm',
    model_version: null,
    metrics: { mae: null, rmse: null, r2: null, accuracy: null, best_val_loss: null },
    tags: [],
    data_job_id: null,
    predictions_available: false
  }
]

// The baseline scenario used to seed scenarioDetailMap. It is NOT part of
// the ModelDetail response (that endpoint sends no `scenarios` array; the
// Results page fetches each scenario by id), so it lives on its own.
const baselineScenario = {
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
    min_risk_score: 0.21
  },
  predictions: [
    {
      source: 'Liquidity Buffer',
      prediction: 0.87,
      risk_score: 0.42,
      confidence_lower: 0.74,
      confidence_upper: 0.95,
      confidence_method: 'split_conformal_alpha_0.1',
      uncertainty_status: 'assessed',
      aleatoric_var: 0.42,
      epistemic_var: 0.05,
      epistemic_share: 0.11,
      explanation: 'Buffer dips under stress but recovers within 10 days.'
    },
    {
      source: 'Cash Burn Rate',
      prediction: 0.21,
      risk_score: 0.36,
      confidence_lower: 0.18,
      confidence_upper: 0.28,
      confidence_method: 'split_conformal_alpha_0.1',
      uncertainty_status: 'not_measurable_single_model',
      explanation: 'Slight acceleration driven by wholesale funding shock.'
    },
    {
      // A refused prediction: the ensemble disagreed on this window more than
      // on any calibration window, so the score, the point prediction and the
      // bounds are all absent -- the row must render dashes and the reason,
      // never a number.
      source: 'FX Swap Basis',
      prediction: null,
      risk_score: null,
      confidence_lower: null,
      confidence_upper: null,
      confidence_method: 'refused_uncertainty_assessment',
      uncertainty_status: 'refused',
      uncertainty_reasons: 'epistemic uncertainty exceeds the calibrated ceiling; the model is extrapolating',
      aleatoric_var: 0.31,
      epistemic_var: 4.2,
      epistemic_share: 0.93,
      explanation: null
    }
  ]
}

// GET /api/models/{id} in the exact ModelDetail shape: model_id, created_at,
// completed_at, status, parameters (the training job's parameter block --
// its `config` carries the hyperparameters), metrics, result, data_job_id,
// predictions_path, visualizations. No `name` here either: the drawer header
// takes the name from the list row.
const modelDetailMap = Object.fromEntries(
  modelsList.map(model => [model.model_id, {
    model_id: model.model_id,
    created_at: model.created_at,
    completed_at: model.created_at,
    status: model.status,
    parameters: {
      data_job_id: model.data_job_id ?? 101,
      train_start: '2023-01-01',
      train_end: '2023-09-30',
      test_start: '2023-10-01',
      test_end: '2023-12-31',
      config: {
        model: model.model_type,
        epochs: 25,
        sequence_length: 30,
        batch_size: 32,
        learning_rate: 0.001,
        dropout: 0.1
      }
    },
    metrics: { ...model.metrics },
    result: {
      model_type: model.model_type,
      model_version: model.model_version,
      test_r2: model.metrics.r2,
      test_rmse: model.metrics.rmse,
      test_mae: model.metrics.mae,
      per_source_metrics: {
        fdic: { rmse: 0.41, mae: 0.19, prediction: 0.72, risk_score: 0.38 },
        ecb: { rmse: 0.45, mae: 0.24, prediction: 0.66, risk_score: 0.44 }
      },
      predictions_path: model.predictions_available
        ? `/var/beacon/models/${model.model_id}/predictions.parquet`
        : null
    },
    data_job_id: model.data_job_id,
    predictions_path: model.predictions_available
      ? `/var/beacon/models/${model.model_id}/predictions.parquet`
      : null,
    visualizations: {}
  }])
)

const scenarioDetailMap = {
  '201:301': baselineScenario,
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
    coverage_description: 'US Depository Institutions',
    sync_interval_minutes: 360,
    consecutive_failures: 0
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
    coverage_description: 'Eurozone banks',
    sync_interval_minutes: 60,
    consecutive_failures: 2
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
    coverage_description: 'Global',
    sync_interval_minutes: null,
    consecutive_failures: 0
  }
]

// The scheduler's view of each feed, as GET /api/v1/data-sources/health
// serves it: cadence, last outcome, next due date, and the backoff factor
// while a feed fails. 402 is deliberately overdue-and-backing-off so the e2e
// run exercises the warning path; 403 is manual-only, so it must never show
// "overdue" -- a feed nobody promised to refresh is not late.
const dataSourceHealth = {
  generated_at: '2024-02-19T12:00:00Z',
  sources: [
    {
      id: 401,
      name: 'FDIC Call Reports',
      plugin_type: 'fdic',
      enabled: true,
      status: 'active',
      error_message: null,
      sync_interval_minutes: 360,
      scheduled: true,
      backoff_factor: 1,
      consecutive_failures: 0,
      last_successful_fetch: '2024-02-14T17:30:00Z',
      last_sync_started_at: '2024-02-14T17:29:12Z',
      last_sync_duration_ms: 48_200,
      last_sync_rows: 128_000,
      collection_running: false,
      next_due_at: '2024-02-19T18:00:00Z',
      overdue: false
    },
    {
      id: 402,
      name: 'ECB Banking',
      plugin_type: 'ecb_banking',
      enabled: true,
      status: 'error',
      error_message: 'connection reset by peer',
      sync_interval_minutes: 60,
      scheduled: true,
      backoff_factor: 4,
      consecutive_failures: 2,
      last_successful_fetch: '2024-02-12T13:00:00Z',
      last_sync_started_at: '2024-02-12T14:05:03Z',
      last_sync_duration_ms: 30_010,
      last_sync_rows: null,
      collection_running: false,
      next_due_at: '2024-02-19T11:00:00Z',
      overdue: true
    },
    {
      id: 403,
      name: 'World Bank Finance',
      plugin_type: 'world_bank',
      enabled: false,
      status: 'disabled',
      error_message: null,
      sync_interval_minutes: null,
      scheduled: false,
      backoff_factor: 1,
      consecutive_failures: 0,
      last_successful_fetch: null,
      last_sync_started_at: null,
      last_sync_duration_ms: null,
      last_sync_rows: null,
      collection_running: false,
      next_due_at: null,
      overdue: false
    }
  ]
}

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

// The header's NotificationBell polls /api/v1/notifications every 30s and its
// /stats companion. Neither was mocked, and because the default GET fallback
// used to answer 200 with an empty object the omission was invisible. Now that
// unknown paths correctly 404, an unmocked endpoint surfaces immediately, so
// these mirror the real NotificationListResponse / NotificationStats schemas.
const notificationsList = [
  {
    id: 1,
    title: 'Model training completed',
    message: 'Liquidity Forecaster finished training.',
    notification_type: 'success',
    priority: 'medium',
    category: 'model',
    is_urgent: false,
    is_read: false,
    is_dismissed: false,
    is_archived: false,
    action_url: '/models',
    action_label: 'View Models',
    related_entity_type: 'job',
    related_entity_id: 101,
    extra_data: {},
    expires_at: null,
    created_at: '2024-02-15T10:20:00Z',
    read_at: null,
    dismissed_at: null
  }
]

const notificationStats = {
  total: notificationsList.length,
  unread: notificationsList.filter((n) => !n.is_read).length,
  by_priority: { medium: 1 },
  by_category: { model: 1 },
  urgent: 0
}

/**
 * Provenance disclosure, as served by `GET /api/v1/data-sources/disclosure`.
 *
 * Shape copied from the real `backend/modules/data/provenance.build_disclosure`
 * output rather than invented: the top-level keys, the six provenance classes,
 * the two policy keys, and the per-source `access` / `deployment` nesting. Only
 * `sources` is shortened -- the real payload lists all 17 registered plugins and
 * four are enough to exercise the page, one per provenance class the UI renders
 * plus `fdic`, which the spec selects in the create-source form.
 *
 * This was missing entirely, which is worth recording because of how it failed.
 * The route fell through to the deliberate "unknown GET path: answer 404, as the
 * real API does" branch at the bottom of the handler. `DataSources.tsx` calls
 * this through `useDataDisclosure`, and TanStack Query *retries* a failed query,
 * so the 404 was re-requested during the create-source mutation's
 * `invalidateQueries(['dataSources'])`. The spec fails the test on any console
 * error, so the retry's 404 threw mid-submit: the POST had already returned 201,
 * but the test died at `expect(dataSourceForm).not.toBeVisible()` with the submit
 * button still `disabled`, because `onClose()` never ran. The trace's network
 * log is what named it -- one `404 GET /api/v1/data-sources/disclosure` among
 * 113 successful requests.
 *
 * The guard that keeps this from recurring is
 * `backend/tests/test_e2e_api_coverage.py`: every `fetchApi` endpoint in
 * `frontend/src` must be answered by this file, so a new backend endpoint the
 * frontend adopts fails a backend test rather than a confusing e2e run.
 */
const dataDisclosure = {
  generated_at: '2026-09-15T00:00:00+00:00',
  policy: {
    synthetic_data:
      'forbidden: the platform does not generate, impute or fabricate observations. A quantity that cannot be computed from real inputs is served as an explicit unavailable state with a reason, never as a plausible-looking placeholder.',
    estimated_inputs:
      'labelled at every surface they appear on (see inferred_inputs) and excluded from the observed-data stores'
  },
  provenance_classes: {
    supervisory_published: 'published by a banking supervisor about the institutions it supervises',
    official_statistics:
      'published by a central bank, statistical agency or intergovernmental body as official statistics',
    regulatory_filings: 'filings made by issuers to a regulator and published by that regulator',
    market_observed:
      'prices and fundamentals observed in markets, typically via a commercial or unofficial aggregator',
    research_dataset:
      "a fixed dataset published for research; provenance and vintage are the dataset's, not a live feed's",
    operator_declared:
      "content supplied or configured by the deploying operator; the platform cannot vouch for its provenance beyond the operator's word"
  },
  sources: [
    {
      plugin_type: 'fdic',
      name: 'FDIC BankFind Suite',
      description:
        'Quarterly US bank supervisory financials (assets, deposits, equity, profitability) from the FDIC -- keyless',
      publisher: 'U.S. Federal Deposit Insurance Corporation',
      provenance_class: 'supervisory_published',
      provides:
        'quarterly bank-level supervisory financials (assets, deposits, equity, profitability) per FDIC CERT via the BankFind Suite API',
      notes: 'served fields verified against the live API on 2026-09-15',
      access: { free: true, key_required: false, registration_url: null },
      deployment: { configured_sources: 1, enabled_sources: 1, catalogue_items: 3 }
    },
    {
      plugin_type: 'ecb',
      name: 'ECB Statistical Data Warehouse',
      description: 'Euro area monetary, banking and financial statistics',
      publisher: 'European Central Bank',
      provenance_class: 'official_statistics',
      provides: 'euro area banking and monetary statistics',
      notes: null,
      access: { free: true, key_required: false, registration_url: null },
      deployment: { configured_sources: 1, enabled_sources: 1, catalogue_items: 2 }
    },
    {
      plugin_type: 'sec_edgar',
      name: 'SEC EDGAR',
      description: 'US issuer filings and XBRL financial statements',
      publisher: 'U.S. Securities and Exchange Commission',
      provenance_class: 'regulatory_filings',
      provides: 'issuer filings and company facts',
      notes: null,
      access: { free: true, key_required: false, registration_url: null },
      deployment: { configured_sources: 0, enabled_sources: 0, catalogue_items: 0 }
    },
    {
      plugin_type: 'yfinance',
      name: 'Yahoo Finance',
      description: 'Equities, FX, crypto and index prices',
      publisher: 'Yahoo Finance (unofficial aggregator)',
      provenance_class: 'market_observed',
      provides: 'market prices used as liquidity proxies',
      notes: null,
      access: { free: true, key_required: false, registration_url: null },
      deployment: { configured_sources: 0, enabled_sources: 0, catalogue_items: 0 }
    }
  ],
  inferred_inputs: [
    {
      name: 'bilateral_exposure_network',
      produced_by: 'POST /api/v1/network/estimate',
      method:
        'maximum-entropy and minimum-support completions of declared aggregate interbank marginals, with Eisenberg-Noe clearing propagated over marginal-preserving structural draws',
      status:
        'estimated: responses carry status=estimated and persistence=not_stored; estimates are never written to the bilateral exposure store and never served as observations',
      caveat:
        'a prior over bilateral structure given the declared aggregates, not a measurement of bilateral exposures; every clearing result computed from it inherits the caveat'
    }
  ],
  undocumented_plugins: [],
  orphaned_configurations: []
}



export async function registerApiMocks(page) {
  // (registerWebfontMocks is gone: the display face is self-hosted under
  // public/fonts/, so the app makes no fonts.googleapis/gstatic requests
  // for the suite to intercept.)

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
        // The real endpoint answers with a bare array on both the bare and the
        // trailing-slash path (List[JobResponse]). An earlier version of this
        // mock replied to the trailing-slash form with {jobs: [...]}, which
        // matched a buggy caller rather than the API and let that bug pass e2e.
        return respond(jobsList)
      }

      const jobDetailMatch = normalizedPath.match(/\/api\/v1\/jobs\/(\d+)$/)
      if (jobDetailMatch) {
        const jobId = Number(jobDetailMatch[1])
        const detail = jobDetailsMap[jobId]
        return respond(detail ?? { id: jobId, job_type: 'unknown', status: 'unknown', progress: 0 })
      }

      const jobQualityMatch = normalizedPath.match(/\/api\/v1\/results\/(\d+)\/data-quality$/)
      if (jobQualityMatch) {
        const jobId = Number(jobQualityMatch[1])
        return respond(jobQualityMap[jobId] ?? {})
      }

      // The backend mounts the model catalogue at both /api/models and
      // /api/v1/models, so the mock mirrors both.
      if (normalizedPath === '/api/models' || normalizedPath === '/api/v1/models') {
        return respond(modelsList)
      }

      const modelDetailMatch = normalizedPath.match(/\/api\/models\/(\d+)$/)
      if (modelDetailMatch) {
        const modelId = Number(modelDetailMatch[1])
        return respond(modelDetailMap[modelId] ?? { model_id: modelId, status: 'completed' })
      }

      const scenarioMatch = normalizedPath.match(/\/api\/models\/(\d+)\/scenarios\/(\d+)$/)
      if (scenarioMatch) {
        const key = `${scenarioMatch[1]}:${scenarioMatch[2]}`
        return respond(scenarioDetailMap[key] ?? null)
      }

      // Predictive-validity report, with the branch logic of the real route:
      // status validated only for a backtest job whose result carries
      // event_metrics, status not_validated (a status, never an error)
      // otherwise. This is the endpoint the coverage audit kept naming as
      // declared by useValidationReport but unanswered by the mock.
      // (Comment style note: the coverage extractor scans this handler body
      // with a brace/quote matcher that does not parse comments, so comments
      // in here carry no apostrophes, backticks, or unbalanced braces.)
      const validationMatch = normalizedPath.match(/\/api\/v2\/reports\/validation\/(\d+)$/)
      if (validationMatch) {
        const jobId = Number(validationMatch[1])
        const job = jobDetailsMap[jobId]
        const eventMetrics = job?.result?.backtest_metrics?.event_metrics
        if (job?.job_type === 'backtest' && eventMetrics) {
          const bySource = eventMetrics.by_source || {}
          const measured = Object.values(bySource).filter(
            (payload) => payload && typeof payload === 'object' && 'roc_auc' in payload
          )
          const aucs = measured.map((payload) => payload.roc_auc).filter((auc) => auc != null)
          return respond({
            job_id: jobId,
            status: 'validated',
            validation: {
              definition: eventMetrics.definition ?? null,
              sources_measured: measured.length,
              sources_skipped: Object.fromEntries(
                Object.entries(bySource).filter(([, payload]) => !(payload && 'roc_auc' in payload))
              ),
              mean_roc_auc: aucs.length ? aucs.reduce((a, b) => a + b, 0) / aucs.length : null,
              by_source: bySource,
              quant_metrics: {
                mse: job.result.backtest_metrics.mse ?? null,
                mae: job.result.backtest_metrics.mae ?? null,
                rmse: job.result.backtest_metrics.rmse ?? null,
                r2: job.result.backtest_metrics.r2 ?? null
              }
            }
          })
        }
        return respond({
          job_id: jobId,
          status: 'not_validated',
          reason:
            'this backtest ran without an event_definition, so no stress ' +
            'events were labelled and no predictive-validity statistics exist',
          validation: null
        })
      }

      if (normalizedPath === '/api/v1/data-sources/disclosure') {
        return respond(dataDisclosure)
      }

      if (normalizedPath === '/api/v1/data-sources/health') {
        return respond(dataSourceHealth)
      }

      if (normalizedPath === '/api/v1/data-sources') {
        return respond(dataSourcesList)
      }

      if (normalizedPath === '/api/v1/system/status') {
        // The dashboard renders measured host status; the mock answers with a
        // fixed, plausible payload so e2e assertions are deterministic.
        return respond({
          status: 'operational',
          cpu: { cores: 8, usage_percent: 12.5 },
          memory: { total_gb: 32.0, used_gb: 11.2, usage_percent: 35.0 },
          gpu: { available: false },
          disk: { total_gb: 512.0, used_gb: 201.4, usage_percent: 39.3 }
        })
      }

      if (normalizedPath === '/api/v1/catalogue') {
        return respond(bankCatalogue)
      }

      if (normalizedPath === '/api/v1/notifications') {
        return respond({
          notifications: notificationsList,
          total: notificationsList.length,
          unread_count: notificationStats.unread
        })
      }

      if (normalizedPath === '/api/v1/notifications/stats') {
        return respond(notificationStats)
      }

      const notificationDetailMatch = normalizedPath.match(/\/api\/v1\/notifications\/(\d+)$/)
      if (notificationDetailMatch) {
        const wanted = Number(notificationDetailMatch[1])
        const found = notificationsList.find((n) => n.id === wanted)
        return respond(found ?? { detail: 'Not Found' }, found ? 200 : 404)
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

      // The risk map now reads live exposures from the backend instead of the
      // bundled fixture. The mock answers the explicit "unavailable" state so
      // the e2e run exercises the no-network path rather than a 404.
      if (normalizedPath === '/api/v1/network/graph') {
        return respond({
          status: 'unavailable',
          as_of: null,
          generated_at: '2024-02-19T12:00:00Z',
          source: 'bilateral_exposure_store',
          unavailable_reason: 'no bilateral exposure matrix has been uploaded',
          nodes: [],
          edges: [],
          layers: [],
          metadata: {
            n_nodes: 0,
            n_edges: 0,
            gross_notional: null,
            geography_resolution: 'client_reference_data',
            risk_score_available: false
          }
        })
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

      // Unknown GET path: answer 404, as the real API does. Returning 200 with
      // an empty object here meant a wrong URL looked like a successful empty
      // result, which is how the broken catalogue URL above stayed hidden.
      return respond({ detail: 'Not Found' }, 404)
    }

    if (method === 'POST') {
      if (normalizedPath === '/api/v1/jobs') {
        const newJobId = jobsList.length + 100
        // The route answers 201 with a full JobResponse, not a bare id.
        return respond(
          {
            id: newJobId,
            job_type: 'data_collection',
            status: 'pending',
            progress: 0,
            parameters: {},
            result: null,
            error_message: null,
            user_friendly_error: null,
            created_at: new Date().toISOString(),
            started_at: null,
            completed_at: null
          },
          201
        )
      }

      if (normalizedPath === '/api/v1/jobs/batch/cancel') {
        // BatchCancelResponse: cancelled ids, failed as reason dicts, and
        // both totals.
        return respond({
          cancelled: jobsList.map(job => job.id),
          failed: [],
          total_requested: jobsList.length,
          total_cancelled: jobsList.length
        })
      }

      if (normalizedPath === '/api/v1/data-sources') {
        return respond({ id: 450, status: 'created' }, 201)
      }

      const syncMatch = normalizedPath.match(/\/api\/v1\/data-sources\/(\d+)\/sync$/)
      if (syncMatch) {
        const sourceId = Number(syncMatch[1])
        // Sync now queues a real collection job (202), it no longer stamps a
        // timestamp: the mock answers in the JobResponse shape the route returns.
        return respond(
          {
            id: 901,
            job_type: 'data_collection',
            status: 'pending',
            progress: 0.0,
            parameters: { data_source_id: sourceId, catalogue_items: [], origin: 'manual' }
          },
          202
        )
      }

      const retryMatch = normalizedPath.match(/\/api\/v1\/jobs\/(\d+)\/retry$/)
      if (retryMatch) {
        // A retry is a NEW job with the same parameters, lineage recorded:
        // the failed job stays a record, not a draft.
        return respond(
          {
            id: 902,
            job_type: 'data_collection',
            status: 'pending',
            progress: 0.0,
            parameters: { retry_of: Number(retryMatch[1]), origin: 'retry' }
          },
          201
        )
      }

      const probeMatch = normalizedPath.match(/\/api\/v1\/data-sources\/(\d+)\/probe$/)
      if (probeMatch) {
        return respond({
          success: true,
          message: 'reachable: provider answered 200',
          details: { latency_ms: 120 }
        })
      }

      if (normalizedPath === '/api/v1/network/exposures') {
        return respond(
          { stored: 4, as_of: '2024-02-01', source_institution: 'mock attribution' },
          201
        )
      }

      if (normalizedPath === '/api/v1/network/estimate') {
        return respond({
          method: 'maximum_entropy_ras',
          nodes: [{ id: 'BANK_A' }, { id: 'BANK_B' }],
          edges: [
            { source: 'BANK_A', target: 'BANK_B', exposure: 55.0, kind: 'estimated' },
            { source: 'BANK_B', target: 'BANK_A', exposure: 45.0, kind: 'estimated' }
          ],
          n_links: 2,
          edges_truncated: false,
          marginal_residual: 0.0,
          uncertainty:
            'estimated completion of declared aggregate marginals: a prior over bilateral structure, not a measurement of bilateral exposures; clearing results inherit this caveat'
        })
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

    if (method === 'DELETE') {
      // Single-job cancellation is DELETE on /api/v1/jobs/<id> -- the POST
      // cancel route earlier mocks answered does not exist (the real API
      // answers 405 there, which is how the UI ended up on DELETE).
      const deleteJobMatch = normalizedPath.match(/\/api\/v1\/jobs\/(\d+)$/)
      if (deleteJobMatch) {
        const jobId = Number(deleteJobMatch[1])
        return respond({ id: jobId, job_type: 'unknown', status: 'cancelled', progress: 0 })
      }
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
