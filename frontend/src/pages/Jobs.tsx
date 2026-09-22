import { useMemo, useState, useEffect, type ChangeEvent, type MouseEvent } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge, { type BadgeVariant } from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useJobs, useJob, useCancelJob, useBatchCancelJobs, useJobDataQuality, useRetryJob } from '../hooks/useApi'
import { useJobsWebSocket } from '../hooks/useJobsWebSocket'
import JobCreationModal from '../components/jobs/JobCreationModal'
import { useRouter } from '../store/useRouter'
import type { EntityId, Job, JobUpdate } from '../types/api'

function JobStatusBadge({ status }: { status?: string | null }) {
  const variants: Record<string, BadgeVariant> = {
    pending: 'default',
    running: 'primary',
    completed: 'success',
    failed: 'danger',
    cancelled: 'warning'
  }

  return (
    <Badge variant={variants[status ?? ''] || 'default'} size="sm">
      {status}
    </Badge>
  )
}

function ProgressBar({ progress }: { progress: number }) {
  return (
    <div className="w-full h-2 bg-bne-paper-dim rounded-full overflow-hidden">
      <div
        className="h-full bg-bne-pine transition-all duration-300"
        style={{ width: `${progress}%` }}
      />
    </div>
  )
}

interface JobRowProps {
  job: Job
  onSelect: (job: Job) => void
  isSelected: boolean
  onCheckboxChange: (jobId: EntityId | undefined) => void
  isChecked: boolean
  showCheckbox: boolean
}

function JobRow({ job, onSelect, isSelected, onCheckboxChange, isChecked, showCheckbox }: JobRowProps) {
  const cancelMutation = useCancelJob()

  const handleCancel = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to cancel this job?')) {
      cancelMutation.mutate(job.job_id || job.id)
    }
  }

  const handleCheckboxClick = (e: ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation()
    onCheckboxChange(job.job_id ?? job.id ?? undefined)
  }

  return (
    <div
      onClick={() => onSelect(job)}
      className={`p-4 rounded-lg border-2 cursor-pointer transition-all ${
        isSelected
          ? 'border-bne-pine bg-bne-pine/5'
          : 'border-bne-line hover:border-bne-pine/50'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 flex-1">
          {showCheckbox && (
            <input
              type="checkbox"
              checked={isChecked}
              onChange={handleCheckboxClick}
              onClick={(e) => e.stopPropagation()}
              className="w-4 h-4 rounded border-bne-line text-bne-pine focus:ring-2 focus:ring-bne-pine"
            />
          )}
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              {/* The list endpoint sends no model reference — every row used
                  to read "Unknown Model" in production. The job type is the
                  real identity of a row. */}
              <h4 className="font-medium text-bne-ink">{job.job_type || 'Job'}</h4>
              <JobStatusBadge status={job.status} />
            </div>
            <p className="text-sm text-bne-muted font-mono">ID: {job.job_id ?? job.id ?? '-'}</p>
          </div>
        </div>
        {(job.status === 'running' || job.status === 'pending') && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
          >
            Cancel
          </Button>
        )}
      </div>

      {job.status === 'running' && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-muted">Progress</span>
            <span className="font-medium text-bne-ink">{job.progress || 0}%</span>
          </div>
          <ProgressBar progress={job.progress || 0} />
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-bne-muted">Started</span>
          <p className="font-medium text-bne-ink">
            {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
          </p>
        </div>
        {job.completed_at && (
          <div>
            <span className="text-bne-muted">Completed</span>
            <p className="font-medium text-bne-ink">
              {new Date(job.completed_at).toLocaleString()}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

interface LossChartProps {
  train?: Array<number | string> | null
  val?: Array<number | string> | null
}

function LossChart({ train = [], val = [] }: LossChartProps) {
  const trainPoints = Array.isArray(train) ? train.map(Number).filter((value) => Number.isFinite(value)) : []
  const valPoints = Array.isArray(val) ? val.map(Number).filter((value) => Number.isFinite(value)) : []
  const series = trainPoints.length || valPoints.length
  if (!series) {
    return <p className="text-sm text-bne-muted">Training history will appear once the first epoch completes.</p>
  }

  const width = 360
  const height = 180
  const padding = 24
  const maxLength = Math.max(trainPoints.length, valPoints.length)
  const combined = [...trainPoints, ...valPoints]
  const maxValue = Math.max(...combined)
  const minValue = Math.min(...combined)
  const effectiveRange = maxValue - minValue || 1

  const buildPoints = (values: number[]) => values.map((value, index) => {
    const xRatio = maxLength > 1 ? index / (maxLength - 1) : 0
    const x = padding + xRatio * (width - padding * 2)
    const yRatio = (value - minValue) / effectiveRange
    const y = height - padding - yRatio * (height - padding * 2)
    return `${x},${y}`
  }).join(' ')

  const gridLines = Array.from({ length: 5 }).map((_, idx) => {
    const ratio = idx / 4
    const y = padding + ratio * (height - padding * 2)
    const value = (maxValue - ratio * effectiveRange).toFixed(4)
    return { y, value }
  })

  return (
    <div className="space-y-3">
      <svg width={width} height={height} className="w-full">
        <rect x={0} y={0} width={width} height={height} fill="white" rx={12} className="stroke-bne-line stroke-1" />
        {gridLines.map((line, index) => (
          <g key={index}>
            <line
              x1={padding}
              y1={line.y}
              x2={width - padding}
              y2={line.y}
              stroke="#E2DAC8"
              strokeDasharray="4 4"
            />
            <text x={8} y={line.y + 4} fontSize="10" fill="#948A72">{line.value}</text>
          </g>
        ))}
        {trainPoints.length > 0 && (
          <polyline
            fill="none"
            stroke="#2C5545"
            strokeWidth={2}
            points={buildPoints(trainPoints)}
          />
        )}
        {valPoints.length > 0 && (
          <polyline
            fill="none"
            stroke="#BE5F2E"
            strokeWidth={2}
            points={buildPoints(valPoints)}
          />
        )}
      </svg>
      <div className="flex items-center gap-6 text-xs text-bne-muted">
        <span className="flex items-center gap-2">
          <span className="h-2 w-8 rounded-full bg-bne-pine" />
          Training loss
        </span>
        <span className="flex items-center gap-2">
          <span className="h-2 w-8 rounded-full bg-bne-ochre" />
          Validation loss
        </span>
      </div>
    </div>
  )
}

interface JobDetailsProps {
  jobId: EntityId
  onOpenModel?: (modelId: EntityId | undefined) => void
  onOpenResults?: (modelId: EntityId | undefined) => void
  onCreateTraining?: (dataJob: Job) => void
  onRetry?: (failedJob: Job) => void
  retryPending?: boolean
}

function JobDetails({ jobId, onOpenModel, onOpenResults, onCreateTraining, onRetry, retryPending = false }: JobDetailsProps) {
  const { data: job, isLoading, error } = useJob(jobId)
  const qualityQuery = useJobDataQuality(jobId, {
    enabled: !!jobId && (job?.job_type === 'data_collection')
  })

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <LoadingSpinner message="Loading job details..." />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent>
          <ErrorMessage error={error} />
        </CardContent>
      </Card>
    )
  }

  if (!job) return null

  const jobResult = job.result || {}
  const isTrainingJob = job.job_type === 'training'
  const isDataCollectionJob = job.job_type === 'data_collection'
  // No transport sends `model_id` on a job row; the real chain is the result
  // blob's model reference, else — for training jobs — the job id itself,
  // which is what the model catalogue keys models by (model_id = job.id).
  const derivedModelId =
    jobResult.model_id ??
    jobResult?.model?.id ??
    (isTrainingJob ? job.id : undefined)
  const qualityData = qualityQuery.data
  // `quality_score` and `completeness` are gate-scale: 0-100 percentages
  // (`QualityPolicy.min_quality_score = 70`, `min_completeness = 80`). This
  // used to guess the unit per value — `numeric > 1 ? numeric : numeric * 100`
  // — so both 0.9 and 92 printed as 90% and neither could be called wrong.
  // A unit that has to be inferred is a unit that will be inferred wrong.
  const formatPercent = (value?: number | null) => {
    if (value === null || value === undefined) return '—'
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '—'
    return `${numeric.toFixed(1)}%`
  }

  const trainingHighlights = isTrainingJob ? [
    { label: 'Best epoch', value: jobResult.best_epoch ? `Epoch ${jobResult.best_epoch}` : '—' },
    { label: 'Final train loss', value: jobResult.final_train_loss?.toFixed(4) ?? '—' },
    { label: 'Final val loss', value: jobResult.final_val_loss?.toFixed(4) ?? '—' },
    { label: 'Test RMSE', value: jobResult.test_rmse?.toFixed(4) ?? '—' },
    { label: 'Test MAE', value: jobResult.test_mae?.toFixed(4) ?? '—' },
    { label: 'Test R²', value: jobResult.test_r2?.toFixed(4) ?? '—' }
  ] : []

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Job Details</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="text-sm text-bne-muted">Job ID</label>
              <p className="font-mono text-sm text-bne-ink mt-1">{job.job_id ?? job.id ?? '-'}</p>
            </div>
            <div>
              <label className="text-sm text-bne-muted">Model</label>
              <p className="font-medium text-bne-ink mt-1">{derivedModelId ?? '—'}</p>
            </div>
            <div>
              <label className="text-sm text-bne-muted">Status</label>
              <div className="mt-1">
                <JobStatusBadge status={job.status} />
              </div>
            </div>
            {job.status === 'running' && (
              <div>
                <label className="text-sm text-bne-muted">Progress</label>
                <div className="mt-2">
                  <ProgressBar progress={job.progress || 0} />
                  <p className="text-sm text-bne-muted mt-1">{job.progress || 0}%</p>
                </div>
              </div>
            )}
            <div>
              <label className="text-sm text-bne-muted">Created</label>
              <p className="text-sm text-bne-ink mt-1">
                {job.created_at ? new Date(job.created_at).toLocaleString() : '-'}
              </p>
            </div>
            {job.started_at && (
              <div>
                <label className="text-sm text-bne-muted">Started</label>
                <p className="text-sm text-bne-ink mt-1">
                  {new Date(job.started_at).toLocaleString()}
                </p>
              </div>
            )}
            {job.completed_at && (
              <div>
                <label className="text-sm text-bne-muted">Completed</label>
                <p className="text-sm text-bne-ink mt-1">
                  {new Date(job.completed_at).toLocaleString()}
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {isDataCollectionJob && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Data quality checks</CardTitle>
              <Button
                size="sm"
                variant="primary"
                onClick={() => onCreateTraining?.(job)}
              >
                Train with this data
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {qualityQuery.isLoading ? (
              <LoadingSpinner message="Evaluating data quality..." />
            ) : qualityData ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="rounded-lg border border-bne-line bg-bne-paper/40 p-4">
                  <p className="text-xs uppercase tracking-wide text-bne-muted">Quality score</p>
                  <p className="text-2xl font-semibold text-bne-ink mt-2">
                    {formatPercent(qualityData.quality_score)}
                  </p>
                  <p className="text-xs text-bne-muted mt-2">
                    Completeness {formatPercent(qualityData.completeness)}
                  </p>
                </div>
                <div className="rounded-lg border border-bne-line bg-bne-paper/40 p-4">
                  <p className="text-xs uppercase tracking-wide text-bne-muted">Anomaly review</p>
                  <p className="text-sm text-bne-ink mt-2">
                    Detected: {qualityData.anomalies_detected ?? 0} · Fixed: {qualityData.anomalies_fixed ?? 0}
                  </p>
                  <p className="text-xs text-bne-muted mt-2">
                    Fit for engine: {qualityData.fit_for_engine ? 'Yes' : 'No'}
                  </p>
                </div>
                {(qualityData.warnings ?? []).length > 0 && (
                  <div className="sm:col-span-2 rounded-lg border border-bne-ochre/30 bg-bne-ochre/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-ochre mb-2">Warnings</p>
                    <ul className="list-disc list-inside text-sm text-bne-ink space-y-1">
                      {(qualityData.warnings ?? []).map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(qualityData.errors ?? []).length > 0 && (
                  <div className="sm:col-span-2 rounded-lg border border-bne-clay/30 bg-bne-clay/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-clay mb-2">Errors</p>
                    <ul className="list-disc list-inside text-sm text-bne-clay space-y-1">
                      {(qualityData.errors ?? []).map((message, index) => (
                        <li key={index}>{message}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-bne-muted">
                Data quality metrics appear once the collection job has finished processing.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {isTrainingJob && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Training performance</CardTitle>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onOpenResults?.(derivedModelId ?? job.id ?? undefined)}
                  disabled={!derivedModelId && !job.id}
                >
                  View model results
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => onOpenModel?.(derivedModelId ?? job.id ?? undefined)}
                  disabled={!derivedModelId && !job.id}
                >
                  Launch what-if scenarios
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-6">
              <LossChart
                train={jobResult.train_loss_history}
                val={jobResult.val_loss_history}
              />
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                {trainingHighlights.map((item) => (
                  <div key={item.label} className="rounded-lg border border-bne-line bg-bne-paper/40 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-muted">{item.label}</p>
                    <p className="font-semibold text-bne-ink mt-2">{item.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* The wire field is `parameters` (JobResponse); nothing sends `config`. */}
      {job.parameters && (
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-bne-paper p-4 rounded-lg text-xs font-mono overflow-x-auto">
              {JSON.stringify(job.parameters, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {(job.error || job.error_message || job.user_friendly_error) && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between w-full">
              <CardTitle>Error Details</CardTitle>
              {job.status === 'failed' && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onRetry?.(job)}
                  loading={retryPending}
                >
                  Retry job
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {/* The translated reason first: it is the one a human can act on.
                The technical string stays, in mono, for the log-driven. */}
            {job.user_friendly_error && (
              <p className="text-sm text-bne-clay mb-3">{job.user_friendly_error}</p>
            )}
            {(job.error || job.error_message) && (
              <div className="bg-bne-clay/5 border border-bne-clay/20 rounded-lg p-4">
                {/* REST calls it error_message, the WebSocket calls it error. */}
                <p className="text-sm text-bne-clay font-mono">{job.error ?? job.error_message}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* The "Logs" card that used to sit here rendered job.logs — a field no
          transport has ever sent (there is no logs column on the Job model).
          It is removed rather than kept as a permanently-empty branch. */}
    </div>
  )
}

/** Defaults the Jobs page hands to the creation modal (e.g. "train with this
 *  data" from a finished collection job). */
interface JobModalDefaults {
  jobType?: string
  dataJobId?: EntityId
}

export default function Jobs() {
  const [selectedJobId, setSelectedJobId] = useState<EntityId | null>(null)
  const [filter, setFilter] = useState('all')
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)
  const [jobModalDefaults, setJobModalDefaults] = useState<JobModalDefaults | null>(null)
  const [selectedJobIds, setSelectedJobIds] = useState<EntityId[]>([])
  const [batchMode, setBatchMode] = useState(false)
  const { data: jobs, isLoading, error, refetch } = useJobs()
  const batchCancelMutation = useBatchCancelJobs()
  const retryMutation = useRetryJob()
  const navigate = useRouter((state) => state.navigate)

  // Enable real-time WebSocket updates
  const { isConnected } = useJobsWebSocket({
    enabled: true,
    onUpdate: (jobUpdate: JobUpdate) => {
      console.log('Job update received:', jobUpdate)
    }
  })

  const filteredJobs = jobs?.filter((job) => {
    if (filter === 'all') return true
    if (filter === 'active') return ['pending', 'running'].includes(job.status)
    return job.status === filter
  }) || []

  const jobTypeLookup = useMemo<Record<string, string>>(() => ({
    data_collection: 'Collect, clean, and stage raw datasets.',
    training: 'Fit a predictive model using a completed data collection job.',
    prediction: 'Generate forward-looking risk scores from a trained model.',
    backtest: 'Replay historical periods to validate performance.'
  }), [])

  // Batch operations handlers
  const handleToggleBatchMode = () => {
    setBatchMode(!batchMode)
    setSelectedJobIds([])
  }

  const handleCheckboxChange = (jobId: EntityId | undefined) => {
    if (jobId === undefined) return
    setSelectedJobIds((prev) =>
      prev.includes(jobId)
        ? prev.filter((id) => id !== jobId)
        : [...prev, jobId]
    )
  }

  const handleSelectAll = () => {
    const cancellableJobs = filteredJobs
      .filter((job) => ['pending', 'running'].includes(job.status))
      .map((job) => job.job_id ?? job.id)
      .filter((id): id is EntityId => id !== null && id !== undefined)
    setSelectedJobIds(cancellableJobs)
  }

  const handleDeselectAll = () => {
    setSelectedJobIds([])
  }

  const handleBatchCancel = async () => {
    if (selectedJobIds.length === 0) return

    if (confirm(`Are you sure you want to cancel ${selectedJobIds.length} job(s)?`)) {
      try {
        const result = await batchCancelMutation.mutateAsync(selectedJobIds)

        if ((result?.failed?.length ?? 0) > 0) {
          alert(
            `Cancelled ${result?.total_cancelled ?? 0} job(s).\n` +
            `Failed to cancel ${result?.failed?.length ?? 0} job(s).`
          )
        } else {
          alert(`Successfully cancelled ${result?.total_cancelled ?? 0} job(s)!`)
        }

        setSelectedJobIds([])
        setBatchMode(false)
      } catch (error) {
        alert(`Batch cancel failed: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }

  // Reset batch selection when filter changes
  useEffect(() => {
    setSelectedJobIds([])
  }, [filter])

  if (isLoading) {
    return (
      <PageContainer title="Jobs">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading jobs..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Jobs">
        <ErrorMessage
          title="Failed to load jobs"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  return (
    <>
      <PageContainer
        title="Jobs"
        subtitle={
          isConnected ? (
            <span className="flex items-center gap-2 text-sm text-bne-moss">
              <span className="w-2 h-2 bg-bne-moss rounded-full animate-pulse"></span>
              Live updates active
            </span>
          ) : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={batchMode ? 'primary' : 'outline'}
              onClick={handleToggleBatchMode}
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              {batchMode ? 'Exit Batch Mode' : 'Batch Operations'}
            </Button>
            <Button variant="primary" onClick={() => setIsJobModalOpen(true)}>
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                New Job
              </span>
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-bne-ink mb-2">What is a job?</h3>
                    <p className="text-sm text-bne-muted leading-relaxed">
                      Jobs are background tasks that move data through Beacon: collecting sources,
                      training models, and running predictions. Track every step here and drill into any failures.
                    </p>
                  </div>
                  <div className="rounded-lg border border-bne-line bg-bne-paper/40 p-4 text-xs text-bne-muted space-y-2">
                    {Object.entries(jobTypeLookup).map(([key, description]) => (
                      <div key={key}>
                        <span className="font-semibold text-bne-ink uppercase tracking-wide">{key.replace(/_/g, ' ')}</span>
                        <p className="mt-1 leading-relaxed">{description}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>

            {batchMode && selectedJobIds.length > 0 && (
              <Card className="bg-bne-pine/10 border-bne-pine">
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <span className="text-sm font-medium text-bne-ink">
                        {selectedJobIds.length} job{selectedJobIds.length !== 1 ? 's' : ''} selected
                      </span>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={handleSelectAll}
                        >
                          Select All
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={handleDeselectAll}
                        >
                          Deselect All
                        </Button>
                      </div>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={handleBatchCancel}
                      disabled={batchCancelMutation.isPending}
                      loading={batchCancelMutation.isPending}
                    >
                      <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                      Cancel Selected
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="flex items-center gap-2">
              <Button
                variant={filter === 'all' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('all')}
              >
                All ({jobs?.length || 0})
              </Button>
              <Button
                variant={filter === 'active' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('active')}
              >
                Active ({jobs?.filter((j) => ['pending', 'running'].includes(j.status)).length || 0})
              </Button>
              <Button
                variant={filter === 'completed' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('completed')}
              >
                Completed ({jobs?.filter((j) => j.status === 'completed').length || 0})
              </Button>
              <Button
                variant={filter === 'failed' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('failed')}
              >
                Failed ({jobs?.filter((j) => j.status === 'failed').length || 0})
              </Button>
            </div>

            {filteredJobs.length === 0 ? (
              <Card className="border-2 border-dashed border-bne-line bg-bne-paper/50">
                <div className="text-center py-12">
                  <svg
                    className="w-16 h-16 mx-auto text-bne-muted/50 mb-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <h3 className="text-lg font-semibold text-bne-ink mb-2">No jobs found</h3>
                  <p className="text-sm text-bne-muted">
                    {filter === 'all'
                      ? 'No jobs have been created yet'
                      : `No jobs with status "${filter}"`}
                  </p>
                </div>
              </Card>
            ) : (
              <div className="space-y-3">
                {filteredJobs.map((job) => {
                  const jobKey = job.job_id ?? job.id
                  return (
                    <JobRow
                      key={String(jobKey)}
                      job={job}
                      onSelect={(j) => setSelectedJobId(j.job_id ?? j.id ?? null)}
                      isSelected={selectedJobId === jobKey}
                      showCheckbox={batchMode}
                      isChecked={jobKey !== undefined && jobKey !== null && selectedJobIds.includes(jobKey)}
                      onCheckboxChange={handleCheckboxChange}
                    />
                  )
                })}
              </div>
            )}
          </div>

          <div className="lg:col-span-1">
            {selectedJobId ? (
              <JobDetails
                jobId={selectedJobId}
                onRetry={(failedJob) => retryMutation.mutate(failedJob.id ?? failedJob.job_id)}
                retryPending={retryMutation.isPending}
                onOpenModel={(modelId) => navigate('results', { modelId: String(modelId) })}
                onOpenResults={(modelId) => navigate('results', { modelId: String(modelId) })}
                onCreateTraining={(dataJob) => {
                  setJobModalDefaults({
                    jobType: 'training',
                    dataJobId: dataJob.id ?? dataJob.job_id ?? undefined
                  })
                  setIsJobModalOpen(true)
                }}
              />
            ) : (
              <Card className="border-2 border-dashed border-bne-line bg-bne-paper/50">
                <div className="text-center py-12">
                  <svg
                    className="w-12 h-12 mx-auto text-bne-muted/50 mb-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <p className="text-sm text-bne-muted">
                    Select a job to view details
                  </p>
                </div>
              </Card>
            )}
          </div>
        </div>
      </PageContainer>
      <JobCreationModal
        isOpen={isJobModalOpen}
        onClose={() => {
          setIsJobModalOpen(false)
          setJobModalDefaults(null)
        }}
        initialJobType={jobModalDefaults?.jobType}
        initialDataJobId={jobModalDefaults?.dataJobId}
      />
    </>
  )
}
