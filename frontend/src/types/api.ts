/**
 * Domain model types for the BEACON API payloads.
 *
 * These interfaces are derived from the response shapes the backend actually
 * serves (see docs/api-endpoints.md, generated from the app's OpenAPI schema)
 * and from every field the UI reads. Fields the API may omit are optional;
 * fields the UI dereferences unguarded after a load/error gate are required.
 * The point of this module is that a payload-envelope or field-name drift —
 * the failure mode that motivated the TypeScript migration in
 * docs/LANGUAGE_STRATEGY.md — becomes a compile error instead of an
 * `undefined%` in production.
 */

/** A backend primary key: tolerate string or number across endpoints. */
export type EntityId = string | number

/* ------------------------------------------------------------------ */
/* Jobs                                                                */
/* ------------------------------------------------------------------ */

/** Lifecycle state of a job. Kept open (`string`) because the UI renders
 *  unknown states through a neutral badge rather than failing. */
export type JobStatus = string

/** Per-source training metrics carried inside a model's `result` blob. */
export interface PerSourceMetrics {
  prediction?: number | null
  forecast?: number | null
  rmse?: number | null
  mae?: number | null
  r2?: number | null
  risk_score?: number | null
  confidence_lower?: number | null
  confidence_upper?: number | null
  explanation?: string | null
  [key: string]: unknown
}

/** Evaluation/training metrics reported by a training job or model detail. */
export interface ModelResultMetrics {
  model_id?: EntityId | null
  model?: { id?: EntityId | null } | null
  test_r2?: number | null
  r2?: number | null
  test_rmse?: number | null
  rmse?: number | null
  test_mae?: number | null
  mae?: number | null
  accuracy?: number | null
  best_epoch?: number | null
  final_train_loss?: number | null
  final_val_loss?: number | null
  train_loss_history?: Array<number | string> | null
  val_loss_history?: Array<number | string> | null
  model_type?: string | null
  model_version?: string | null
  config?: ({ model_type?: string | null } & Record<string, unknown>) | null
  executive_summary?: string | null
  per_source_metrics?: Record<string, PerSourceMetrics> | null
  [key: string]: unknown
}

/** Parameters a job was created with (shape varies by job type). */
export interface JobParameters {
  regions?: string[]
  countries?: string[]
  start_date?: string
  end_date?: string
  catalogue_items?: EntityId[]
  data_job_id?: number
  train_start?: string
  train_end?: string
  test_start?: string
  test_end?: string
  config?: Record<string, unknown>
  trained_model_job?: number
  event_definition?: EventDefinitionInput
  [key: string]: unknown
}

/** A job row from `/v1/jobs` (bare array envelope) and `/v1/jobs/{id}`.
 *
 *  Field set = JobResponse (REST) ∪ job_payload (WebSocket), and nothing
 *  else: an earlier revision of this interface also declared `name`,
 *  `model_id`, `config` and `logs`, none of which any transport sends — the
 *  UI read them, the e2e mock dutifully served them, and production rendered
 *  "Unknown Model" and empty cards. The contract test
 *  (backend/tests/test_frontend_contract.py) now pins this interface to the
 *  live OpenAPI schema, with the two WS-only spellings allowlisted. */
export interface Job {
  id?: EntityId | null
  /** WebSocket payloads carry both `id` and `job_id` (the two react-query
   *  caches are keyed differently); REST sends only `id`. */
  job_id?: EntityId | null
  job_type?: string | null
  status: JobStatus
  progress?: number | null
  created_at?: string | null
  started_at?: string | null
  completed_at?: string | null
  result?: ModelResultMetrics | null
  parameters?: JobParameters | null
  /** WebSocket names the technical string `error`; REST names it
   *  `error_message`. JobDetails reads both. */
  error?: string | null
  error_message?: string | null
  user_friendly_error?: string | null
}

/** One entry of a batch-cancel failure: the job id plus the reason it could
 *  not be cancelled (BatchCancelResponse.failed is a list of dicts, not ids). */
export type BatchCancelFailure = Record<string, unknown>

/** Response of `POST /v1/jobs/batch/cancel`. */
export interface BatchCancelResult {
  cancelled: EntityId[]
  failed: BatchCancelFailure[]
  total_requested: number
  total_cancelled: number
}

/** Payload for `POST /v1/jobs`. */
export interface JobCreatePayload {
  name: string
  description?: string
  job_type: string
  parameters: JobParameters
  scheduled: boolean
}

/** Event definition declared on a backtest job. */
export interface EventDefinitionInput {
  direction: string
  quantile: number
  horizon: number
  min_duration: number
}

/** `GET /v1/results/{jobId}/data-quality` for a collection job. */
export interface JobDataQualityReport {
  quality_score?: number | null
  completeness?: number | null
  anomalies_detected?: number | null
  anomalies_fixed?: number | null
  fit_for_engine?: boolean | null
  warnings?: string[] | null
  errors?: string[] | null
}

/** Incremental job state pushed over the jobs WebSocket. Carries both `id`
 *  and `job_id` because the two react-query caches are keyed differently. */
export interface JobUpdate {
  id?: EntityId | null
  job_id?: EntityId | null
  status?: JobStatus
  progress?: number | null
  [key: string]: unknown
}

/* ------------------------------------------------------------------ */
/* Models                                                              */
/* ------------------------------------------------------------------ */

/** Evaluation metrics as the model catalogue reports them (`ModelMetrics`). */
export interface ModelMetrics {
  mae?: number | null
  rmse?: number | null
  r2?: number | null
  accuracy?: number | null
  best_val_loss?: number | null
}

/** A row of `GET /models` (`ModelSummary`): completed training jobs that can
 *  serve as models. NOTE: the list endpoint only ever returns completed
 *  training jobs, and it has no `description`, `architecture`,
 *  `input_features`, `prediction_steps` or `last_trained` — an earlier single
 *  `Model` interface declared them, and the cards that read them rendered
 *  invented defaults ("LSTM", 12, 4) in production. */
export interface ModelSummary {
  model_id: EntityId
  name: string
  created_at?: string | null
  status: string
  model_type?: string | null
  model_version?: string | null
  metrics?: ModelMetrics | null
  tags?: string[] | null
  data_job_id?: EntityId | null
  predictions_available?: boolean | null
}

/** `GET /models/{id}` (`ModelDetail`). `parameters` is the training job's
 *  parameter block (its `config` sub-object carries the hyperparameters);
 *  `metrics`/`result` are declared Dict[str, Any] on the backend, so they are
 *  typed structurally here and left open where the engine's output is. */
export interface ModelDetailData {
  model_id: EntityId
  created_at?: string | null
  completed_at?: string | null
  status: string
  parameters?: (JobParameters & Record<string, unknown>) | null
  metrics?: ModelMetrics | null
  result?: ModelResultMetrics | null
  data_job_id?: EntityId | null
  predictions_path?: string | null
  visualizations?: Record<string, unknown> | null
}

/* ------------------------------------------------------------------ */
/* Scenarios (what-if simulation)                                      */
/* ------------------------------------------------------------------ */

export interface ScenarioAdjustment {
  source: string
  type: string
  value: number
}

export interface ScenarioSummary {
  avg_risk_score?: number | null
  max_risk_score?: number | null
  min_risk_score?: number | null
  num_series?: number | null
}

export interface ScenarioPrediction {
  source?: string | null
  bank_id?: EntityId | null
  bank_name?: string | null
  prediction?: number | null
  risk_score?: number | null
  overall_risk?: number | null
  confidence_lower?: number | null
  confidence_upper?: number | null
  confidence_method?: string | null
  explanation?: string | null
  /* Uncertainty decomposition (deep-ensemble runs; absent on scenarios
   * saved before the wiring or from single-checkpoint models, where the
   * status says the split is not measurable). A refused row carries null
   * prediction/risk_score/bounds and the reasons here -- absence, not 0. */
  uncertainty_status?: string | null
  uncertainty_reasons?: string | null
  aleatoric_var?: number | null
  epistemic_var?: number | null
  epistemic_share?: number | null
}

/** Response of `POST /api/models/{id}/simulate` and
 *  `GET /api/models/{id}/scenarios/{scenarioId}`. */
export interface ScenarioResult {
  scenario_id?: EntityId | null
  name?: string | null
  horizon_days?: number | null
  created_at?: string | null
  storage_path?: string | null
  adjustments?: ScenarioAdjustment[] | null
  summary?: ScenarioSummary | null
  predictions?: ScenarioPrediction[] | null
  feature_importances?: Record<string, number | string> | null
  executive_summary?: string | null
}

/* ------------------------------------------------------------------ */
/* Predictive validity (backtest reports)                              */
/* ------------------------------------------------------------------ */

export interface ValidationSourceStats {
  roc_auc?: number | null
  average_precision?: number | null
  n_events?: number | null
  lead_time?: { median_lead?: number | null; n_zero_lead?: number | null } | null
  skipped?: string | null
}

export interface ValidationBlock {
  definition?: (Partial<EventDefinitionInput> & Record<string, unknown>) | null
  sources_measured?: number | null
  mean_roc_auc?: number | null
  by_source?: Record<string, ValidationSourceStats | null> | null
}

/** `GET /v2/reports/validation/{jobId}`. Absence of validation is a status
 *  ("not_validated"), never an error. */
export interface ValidationReport {
  status: string
  reason?: string | null
  validation?: ValidationBlock | null
}

/** One loss cell of the volatility track: mean squared error of the one-step
 *  conditional variance, and mean absolute error of volatility, both averaged
 *  over the held-out steps of embargoed walk-forward folds. */
export interface VolatilityLossCell {
  mse_var?: number | null
  mae_vol?: number | null
}

/** Per-source entry of run_backtest's volatility track (wired in job_tasks
 *  from backtesting.compare_volatility_baselines into
 *  result.backtest_metrics.volatility_baselines.by_source). A source either
 *  gets the summary — positive lift means GARCH(1,1) beat unconditional
 *  variance on that loss — or a declared skip, or a recorded failure. The
 *  three states the track can honestly be in; none of them is an error. */
export interface VolatilityBaselineEntry {
  skipped?: string | null
  failed?: string | null
  n_folds?: number | null
  n_scored_folds?: number | null
  n_fit_failures?: number | null
  n_nonstationary_fits?: number | null
  n_nonconverged_fits?: number | null
  garch?: VolatilityLossCell | null
  unconditional?: VolatilityLossCell | null
  lift?: VolatilityLossCell | null
  folds?: unknown[] | null
  [key: string]: unknown
}

/** GET /api/v2/reports/backtest/{job_id} — the full backtest report
 *  (backend/schemas/predictions_v2.BacktestReport). Jobs that are not
 *  completed answer the progress payload instead: status + progress, no
 *  metrics. Absence of metrics is a status, never an error wall. */
export interface BacktestReport {
  job_id?: EntityId | null
  status?: string | null
  progress?: number | null
  current_step?: string | null
  metrics?: (Record<string, unknown> & {
    volatility_baselines?: { by_source?: Record<string, VolatilityBaselineEntry | null> | null } | null
  }) | null
  metadata?: Record<string, unknown> | null
  quant_metrics?: Record<string, unknown> | null
  walk_forward?: Record<string, unknown> | null
  [key: string]: unknown
}

/* ------------------------------------------------------------------ */
/* Data sources, catalogue, disclosure                                 */
/* ------------------------------------------------------------------ */

/** A configured data source row from `/v1/data-sources`
 *  (`DataSourceResponse` = `DataSourceConfigBase` + status/telemetry). An
 *  earlier revision also declared source_id, source_name, plugin_name, type,
 *  record_count, last_updated, coverage and api_endpoint — invented
 *  alternates the UI fell back through; every one rendered undefined in
 *  production while the mock served some of them. */
export interface DataSource {
  id: EntityId
  name: string
  plugin_type: string
  config?: Record<string, unknown> | null
  description?: string | null
  enabled?: boolean | null
  registration_url?: string | null
  registration_required?: boolean | null
  free_tier_limits?: string | null
  coverage_description?: string | null
  status?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  last_successful_fetch?: string | null
  sync_interval_minutes?: number | null
  consecutive_failures?: number | null
  last_sync_started_at?: string | null
  last_sync_duration_ms?: number | null
  last_sync_rows?: number | null
}

/** Scheduler's view of one feed, from `/v1/data-sources/health`. */
export interface DataSourceHealthRow {
  id: EntityId
  name?: string | null
  scheduled: boolean
  sync_interval_minutes?: number | null
  backoff_factor?: number | null
  consecutive_failures?: number | null
  last_successful_fetch?: string | null
  last_sync_started_at?: string | null
  last_sync_duration_ms?: number | null
  last_sync_rows?: number | null
  next_due_at?: string | null
  collection_running?: boolean | null
  overdue?: boolean | null
  error_message?: string | null
}

/** `GET /v1/data-sources/health` envelope. */
export interface DataSourceHealthPayload {
  sources: DataSourceHealthRow[]
}

/** `POST /v1/data-sources/{id}/probe` result. */
export interface ProbeResult {
  success?: boolean | null
  message?: string | null
  [key: string]: unknown
}

/** The form payload for creating/updating a data source. */
export interface DataSourceFormPayload {
  name: string
  plugin_type: string
  description: string | null
  enabled: boolean
  registration_url: string | null
  registration_required: boolean
  free_tier_limits: string | null
  coverage_description: string | null
  config: Record<string, unknown>
}

/** A plugin selectable in the source form, derived from the disclosure
 *  registry (never a hand-maintained frontend list). */
export interface PluginOption {
  value: string
  label: string
}

/** A catalogue dataset row from `/v1/catalogue`
 *  (`DataCatalogueItemResponse`). An earlier revision also declared
 *  country/country_code, update_frequency, coverage_end, parameters,
 *  metadata, sample_metrics and source_name — none of which the schema
 *  sends — and three screens rendered branches off them that could never
 *  be true in production. */
export interface CatalogueItem {
  id: EntityId
  code: string
  name: string
  description?: string | null
  category?: string | null
  region?: string | null
  risk_types?: string[] | null
  data_source_id?: EntityId | null
  data_source?: {
    id?: EntityId | null
    name?: string | null
    plugin_type?: string | null
    description?: string | null
  } | null
  endpoint?: string | null
  frequency?: string | null
  granularity?: string | null
  unit?: string | null
  enabled?: boolean | null
  default_selected?: boolean | null
  priority?: number | null
  tags?: string[] | null
  created_at?: string | null
  updated_at?: string | null
  last_data_update?: string | null
}

/** Query filters for the catalogue endpoint. */
export interface CatalogueFilters {
  category?: string
  region?: string
  countries?: string[]
  sources?: string[]
  risk_type?: string
  search?: string
  enabled_only?: boolean
  default_only?: boolean
}

/** The flattened bank/dataset row the risk map consumes
 *  (produced by `useBanksByRegion`). */
export interface BankSummary {
  id: EntityId
  code?: string | null
  name?: string | null
  category?: string | null
  country?: string | null
  region?: string | null
  description?: string | null
  /** The catalogue carries no per-item risk channel (the old mapping read
   *  `parameters.risk_score` off a field the schema does not send), so this
   *  is null until an endpoint reports one. The map renders null as its
   *  neutral colour and the region panel renders it as "—" — a risk score
   *  is never inferred. */
  risk_score?: number | string | null
  source?: string
}

/** A dataset pinned for job creation (details modal → data sources page). */
export interface SelectedDataset {
  id: EntityId
  code?: string | null
  name?: string | null
  category?: string | null
  region?: string | null
}

/** One source entry in the provenance disclosure payload. */
export interface DisclosureSource {
  plugin_type: string
  name?: string | null
  publisher?: string | null
  provenance_class: string
  provides?: string | null
  notes?: string | null
  access?: { key_required?: boolean | null } | null
  deployment?: {
    configured_sources?: number | null
    catalogue_items?: number | null
  } | null
}

/** A quantity the platform estimates rather than observes. */
export interface InferredInputDisclosure {
  name: string
  produced_by?: string | null
  method?: string | null
  caveat?: string | null
}

/** A stored configuration whose plugin can no longer fetch. */
export interface OrphanedConfiguration {
  plugin_type: string
  problem?: string | null
}

/** `GET /v1/data-sources/disclosure`. */
export interface DataDisclosure {
  policy?: { synthetic_data?: string | null } | null
  sources?: DisclosureSource[] | null
  inferred_inputs?: InferredInputDisclosure[] | null
  orphaned_configurations?: OrphanedConfiguration[] | null
}

/* ------------------------------------------------------------------ */
/* Network graph                                                       */
/* ------------------------------------------------------------------ */

export interface NetworkNode {
  id: string
  [key: string]: unknown
}

/** One exposure edge from `GET /v1/network/graph`. */
export interface NetworkEdge {
  id: string
  source: string
  target: string
  exposure: number | string
  risk_score?: number | null
  layer?: string | null
  kind?: string | null
}

/** Raw `GET /v1/network/graph` payload. 200 with `status: "unavailable"` is
 *  a first-class state, not an error. */
export interface NetworkGraphPayload {
  status?: string | null
  as_of?: string | null
  generated_at?: string | null
  source?: string | null
  unavailable_reason?: string | null
  nodes?: NetworkNode[] | null
  edges?: NetworkEdge[] | null
  layers?: unknown[] | null
  metadata?: Record<string, unknown> | null
}

/** The decoded graph the map components render (see normalizeNetworkGraph). */
export interface NormalizedNetworkGraph {
  status: 'available' | 'unavailable'
  asOf: string | null
  generatedAt: string | null
  source: string | null
  reason: string | null
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  layers: unknown[]
  metadata: Record<string, unknown>
}

/** One rendered exposure corridor: an API edge or a fixture connection,
 *  normalised to a single shape (the map must never guess which it holds). */
export interface ConnectionView {
  id: string
  source: string
  target: string
  exposure: number
  riskScore: number | null
  transactionVolume?: number
  layer?: string | null
  kind?: string | null
}

/** Response of `POST /v1/network/estimate` (maximum-entropy completion). */
export interface NetworkEstimateResult {
  n_links?: number | null
  edges?: unknown[] | null
  method?: string | null
  uncertainty?: string | null
  [key: string]: unknown
}

/* ------------------------------------------------------------------ */
/* System status                                                       */
/* ------------------------------------------------------------------ */

export interface HostResourceMetric {
  usage_percent?: number | null
  cores?: number | null
  used_gb?: number | string | null
  total_gb?: number | string | null
}

/** `GET /v1/system/status` — measured host state, never invented. */
export interface SystemStatus {
  status?: string | null
  cpu?: HostResourceMetric | null
  memory?: HostResourceMetric | null
  disk?: HostResourceMetric | null
  gpu?: { available?: boolean | null; count?: number | null } | null
  version?: string | null
  git_revision?: string | null
  auth?: { mode?: string | null } | null
}

/* ------------------------------------------------------------------ */
/* Data quality                                                        */
/* ------------------------------------------------------------------ */

export interface DataQualityOverview {
  overall_health: number
  active_sources: number
  total_sources: number
}

export interface DataQualityFreshness {
  fresh: number
  stale: number
  outdated: number
  never_synced: number
  freshness_percentage: number
}

export interface DataQualityScores {
  avg_quality_score: number
  avg_completeness?: number | null
  jobs_analyzed: number
}

export interface DataQualityAnomalies {
  low_quality_jobs: number
  error_sources: number
  recent_failures: number
  stale_sources: number
}

/** `GET /v1/data-quality/stats`. */
export interface DataQualityStats {
  overview: DataQualityOverview
  freshness: DataQualityFreshness
  quality: DataQualityScores
  anomalies: DataQualityAnomalies
}

/** One row of `GET /v1/data-quality/sources`. */
export interface SourceQualityRow {
  id: EntityId
  name?: string | null
  plugin_type?: string | null
  status?: string | null
  enabled?: boolean | null
  freshness_status: string
  days_since_update: number | null
  avg_quality_score: number | null
  last_fetch?: string | null
}

/** One point of `GET /v1/data-quality/trends`. */
export interface QualityTrendPoint {
  date: string
  avg_quality_score: number
}

/** `GET /v1/data-quality/trends` envelope. */
export interface QualityTrendsPayload {
  trends: QualityTrendPoint[]
}

/* ------------------------------------------------------------------ */
/* Analytics                                                           */
/* ------------------------------------------------------------------ */

export interface AnalyticsJobStats {
  total?: number | null
  completed?: number | null
  failed?: number | null
  success_rate?: number | null
  avg_execution_time?: number | null
  distribution?: Record<string, number> | null
}

export interface AnalyticsModelStats {
  health_percentage?: number | null
  ready?: number | null
  total?: number | null
}

export interface AnalyticsDataQualityStats {
  avg_quality_score?: number | null
  avg_completeness?: number | null
  jobs_analyzed?: number | null
}

/** `GET /v1/analytics/overview`. */
export interface AnalyticsOverview {
  jobs?: AnalyticsJobStats | null
  models?: AnalyticsModelStats | null
  data_quality?: AnalyticsDataQualityStats | null
}

/** One point of the time-series trends endpoint. */
export interface TimeSeriesPoint {
  date: string
  value: number
}

/** `GET /v1/analytics/trends/time-series` envelope. */
export interface TimeSeriesPayload {
  series?: TimeSeriesPoint[] | null
}

/** One detected anomaly from the insights endpoint. */
export interface AnomalyInsight {
  severity: string
  type: string
  message?: string | null
  detected_at?: string | null
}

/** `GET /v1/analytics/insights/anomalies` envelope. */
export interface AnomalyInsightsPayload {
  anomalies_detected?: number | null
  anomalies?: AnomalyInsight[] | null
}

/* ------------------------------------------------------------------ */
/* Countries                                                           */
/* ------------------------------------------------------------------ */

/** One country row of the `/v1/countries/` list envelope. */
export interface Country {
  id: EntityId
  country_name: string
  country_code: string
  region?: string | null
  sub_region?: string | null
  capital?: string | null
  currency?: string | null
  population?: number | string | null
  gdp_usd?: number | string | null
  gdp_per_capita?: number | string | null
  gdp_growth_rate?: number | string | null
  inflation_rate?: number | string | null
  unemployment_rate?: number | string | null
  credit_to_gdp?: number | string | null
  debt_to_gdp?: number | string | null
  fiscal_balance?: number | string | null
  current_account_balance?: number | string | null
  bank_count?: number | string | null
  total_bank_assets_usd?: number | string | null
  risk_level?: string | null
  risk_score?: number | string | null
  last_updated?: string | null
}

/** `GET /v1/countries/` wrapper envelope. */
export interface CountryListResponse {
  countries: Country[]
  total?: number | null
}

/* ------------------------------------------------------------------ */
/* Notifications                                                       */
/* ------------------------------------------------------------------ */

/** One notification row. */
export interface Notification {
  id: EntityId
  title?: string | null
  message?: string | null
  notification_type?: string | null
  category?: string | null
  priority?: string | null
  is_read?: boolean | null
  is_urgent?: boolean | null
  action_url?: string | null
  action_label?: string | null
  created_at?: string | null
}

/** `GET /v1/notifications` envelope. */
export interface NotificationsResponse {
  notifications?: Notification[] | null
  unread_count?: number | null
  total?: number | null
}

/** A notification id is a backend primary key; tolerate string or number. */
export type NotificationId = EntityId
