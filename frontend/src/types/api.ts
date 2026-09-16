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

/** One line of a job's captured log output. */
export interface JobLogEntry {
  timestamp?: string | null
  message?: string | null
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

/** A job row from `/v1/jobs` (bare array envelope) and `/v1/jobs/{id}`. */
export interface Job {
  id?: EntityId | null
  job_id?: EntityId | null
  name?: string | null
  job_type?: string | null
  /** Legacy camelCase spelling tolerated by the job-type filter. */
  jobType?: string | null
  status: JobStatus
  progress?: number | null
  created_at?: string | null
  started_at?: string | null
  completed_at?: string | null
  model_id?: EntityId | null
  result?: ModelResultMetrics | null
  config?: Record<string, unknown> | null
  parameters?: JobParameters | null
  error?: string | null
  user_friendly_error?: string | null
  logs?: JobLogEntry[] | null
}

/** Response of `POST /v1/jobs/batch/cancel`. */
export interface BatchCancelResult {
  cancelled: EntityId[]
  failed: EntityId[]
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

/** A model row from `/models` (bare array) and `/models/{id}`. */
export interface Model {
  id?: EntityId | null
  model_id: EntityId
  name?: string | null
  description?: string | null
  model_type?: string | null
  model_version?: string | null
  architecture?: string | null
  input_features?: number | null
  prediction_steps?: number | null
  status?: string | null
  accuracy?: number | null
  last_trained?: string | null
  created_at?: string | null
  completed_at?: string | null
  data_job_id?: EntityId | null
  predictions_path?: string | null
  hyperparameters?: Record<string, unknown> | null
  metrics?: ModelResultMetrics | null
  data_summary?: Record<string, unknown> | null
  result?: ModelResultMetrics | null
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
  explanation?: string | null
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

/* ------------------------------------------------------------------ */
/* Data sources, catalogue, disclosure                                 */
/* ------------------------------------------------------------------ */

/** A configured data source row from `/v1/data-sources` (bare array). */
export interface DataSource {
  id?: EntityId | null
  source_id?: EntityId | null
  name?: string | null
  source_name?: string | null
  plugin_type?: string | null
  plugin_name?: string | null
  type?: string | null
  description?: string | null
  status?: string | null
  enabled?: boolean | null
  record_count?: number | null
  sync_interval_minutes?: number | null
  created_at?: string | null
  updated_at?: string | null
  last_updated?: string | null
  last_successful_fetch?: string | null
  registration_url?: string | null
  registration_required?: boolean | null
  free_tier_limits?: string | null
  coverage_description?: string | null
  coverage?: string | null
  config?: Record<string, unknown> | null
  api_endpoint?: string | null
  error_message?: string | null
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

/** A catalogue dataset row from `/v1/catalogue` (bare array). */
export interface CatalogueItem {
  id: EntityId
  code?: string | null
  name?: string | null
  category?: string | null
  region?: string | null
  description?: string | null
  country?: string | null
  country_code?: string | null
  frequency?: string | null
  update_frequency?: string | null
  unit?: string | null
  last_updated?: string | null
  coverage_end?: string | null
  parameters?: Record<string, unknown> | null
  metadata?: Record<string, unknown> | null
  sample_metrics?: Record<string, string | number> | null
  data_source?: { id?: EntityId | null; name?: string | null } | null
  data_source_id?: EntityId | null
  source_name?: string | null
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
  metadata?: Record<string, unknown>
  /** Dynamic metadata: the backend may report a number or numeric string. */
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
