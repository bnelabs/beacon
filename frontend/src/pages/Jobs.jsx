import { useMemo, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useJobs, useJob, useCancelJob, useJobDataQuality } from '../hooks/useApi'
import JobCreationModal from '../components/jobs/JobCreationModal'
import { useRouter } from '../store/useRouter'

function JobStatusBadge({ status }) {
  const variants = {
    pending: 'default',
    running: 'primary',
    completed: 'success',
    failed: 'danger',
    cancelled: 'warning'
  }

  return (
    <Badge variant={variants[status] || 'default'} size="sm">
      {status}
    </Badge>
  )
}

function ProgressBar({ progress }) {
  return (
    <div className="w-full h-2 bg-bne-frost rounded-full overflow-hidden">
      <div
        className="h-full bg-bne-azure transition-all duration-300"
        style={{ width: `${progress}%` }}
      />
    </div>
  )
}

function JobRow({ job, onSelect, isSelected }) {
  const cancelMutation = useCancelJob()

  const handleCancel = (e) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to cancel this job?')) {
      cancelMutation.mutate(job.job_id || job.id)
    }
  }

  return (
    <div
      onClick={() => onSelect(job)}
      className={`p-4 rounded-lg border-2 cursor-pointer transition-all ${
        isSelected
          ? 'border-bne-azure bg-bne-azure/5'
          : 'border-bne-frost hover:border-bne-azure/50'
      }`}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h4 className="font-medium text-bne-ink">{job.model_id || 'Unknown Model'}</h4>
            <JobStatusBadge status={job.status} />
          </div>
          <p className="text-sm text-bne-steel font-mono">ID: {job.job_id ?? job.id ?? '-'}</p>
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
            <span className="text-bne-steel">Progress</span>
            <span className="font-medium text-bne-ink">{job.progress || 0}%</span>
          </div>
          <ProgressBar progress={job.progress || 0} />
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-bne-steel">Started</span>
          <p className="font-medium text-bne-ink">
            {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
          </p>
        </div>
        {job.completed_at && (
          <div>
            <span className="text-bne-steel">Completed</span>
            <p className="font-medium text-bne-ink">
              {new Date(job.completed_at).toLocaleString()}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function LossChart({ train = [], val = [] }) {
  const trainPoints = Array.isArray(train) ? train.map(Number).filter((value) => Number.isFinite(value)) : []
  const valPoints = Array.isArray(val) ? val.map(Number).filter((value) => Number.isFinite(value)) : []
  const series = trainPoints.length || valPoints.length
  if (!series) {
    return <p className="text-sm text-bne-steel">Training history will appear once the first epoch completes.</p>
  }

  const width = 360
  const height = 180
  const padding = 24
  const maxLength = Math.max(trainPoints.length, valPoints.length)
  const combined = [...trainPoints, ...valPoints]
  const maxValue = Math.max(...combined)
  const minValue = Math.min(...combined)
  const effectiveRange = maxValue - minValue || 1

  const buildPoints = (values) => values.map((value, index) => {
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
        <rect x={0} y={0} width={width} height={height} fill="white" rx={12} className="stroke-bne-frost stroke-1" />
        {gridLines.map((line, index) => (
          <g key={index}>
            <line
              x1={padding}
              y1={line.y}
              x2={width - padding}
              y2={line.y}
              stroke="#E5ECF6"
              strokeDasharray="4 4"
            />
            <text x={8} y={line.y + 4} fontSize="10" fill="#7A8CA6">{line.value}</text>
          </g>
        ))}
        {trainPoints.length > 0 && (
          <polyline
            fill="none"
            stroke="#2563EB"
            strokeWidth={2}
            points={buildPoints(trainPoints)}
          />
        )}
        {valPoints.length > 0 && (
          <polyline
            fill="none"
            stroke="#F97316"
            strokeWidth={2}
            points={buildPoints(valPoints)}
          />
        )}
      </svg>
      <div className="flex items-center gap-6 text-xs text-bne-steel">
        <span className="flex items-center gap-2">
          <span className="h-2 w-8 rounded-full bg-bne-azure" />
          Training loss
        </span>
        <span className="flex items-center gap-2">
          <span className="h-2 w-8 rounded-full bg-bne-amber" />
          Validation loss
        </span>
      </div>
    </div>
  )
}

function JobDetails({ jobId, onOpenModel, onOpenResults, onCreateTraining }) {
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
  const derivedModelId =
    job.model_id ??
    jobResult.model_id ??
    jobResult?.model?.id ??
    (isTrainingJob ? job.id : undefined)
  const qualityData = qualityQuery.data
  const showQuality = isDataCollectionJob && qualityData

  const formatPercent = (value) => {
    if (value === null || value === undefined) return '—'
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return '—'
    const scaled = numeric > 1 ? numeric : numeric * 100
    return `${Math.round(scaled)}%`
  }

  const trainingHighlights = isTrainingJob ? [
    { label: 'Best epoch', value: jobResult.best_epoch ? `Epoch ${jobResult.best_epoch}` : '—' },
    { label: 'Final train loss', value: jobResult.final_train_loss?.toFixed?.(4) ?? '—' },
    { label: 'Final val loss', value: jobResult.final_val_loss?.toFixed?.(4) ?? '—' },
    { label: 'Test RMSE', value: jobResult.test_rmse?.toFixed?.(4) ?? '—' },
    { label: 'Test MAE', value: jobResult.test_mae?.toFixed?.(4) ?? '—' },
    { label: 'Test R²', value: jobResult.test_r2?.toFixed?.(4) ?? '—' }
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
              <label className="text-sm text-bne-steel">Job ID</label>
              <p className="font-mono text-sm text-bne-ink mt-1">{job.job_id ?? job.id ?? '-'}</p>
            </div>
            <div>
              <label className="text-sm text-bne-steel">Model</label>
              <p className="font-medium text-bne-ink mt-1">{job.model_id}</p>
            </div>
            <div>
              <label className="text-sm text-bne-steel">Status</label>
              <div className="mt-1">
                <JobStatusBadge status={job.status} />
              </div>
            </div>
            {job.status === 'running' && (
              <div>
                <label className="text-sm text-bne-steel">Progress</label>
                <div className="mt-2">
                  <ProgressBar progress={job.progress || 0} />
                  <p className="text-sm text-bne-steel mt-1">{job.progress || 0}%</p>
                </div>
              </div>
            )}
            <div>
              <label className="text-sm text-bne-steel">Created</label>
              <p className="text-sm text-bne-ink mt-1">
                {job.created_at ? new Date(job.created_at).toLocaleString() : '-'}
              </p>
            </div>
            {job.started_at && (
              <div>
                <label className="text-sm text-bne-steel">Started</label>
                <p className="text-sm text-bne-ink mt-1">
                  {new Date(job.started_at).toLocaleString()}
                </p>
              </div>
            )}
            {job.completed_at && (
              <div>
                <label className="text-sm text-bne-steel">Completed</label>
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
            ) : showQuality ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="rounded-lg border border-bne-frost bg-bne-ice/40 p-4">
                  <p className="text-xs uppercase tracking-wide text-bne-steel">Quality score</p>
                  <p className="text-2xl font-semibold text-bne-ink mt-2">
                    {formatPercent(qualityData.quality_score)}
                  </p>
                  <p className="text-xs text-bne-steel mt-2">
                    Completeness {formatPercent(qualityData.completeness)}
                  </p>
                </div>
                <div className="rounded-lg border border-bne-frost bg-bne-ice/40 p-4">
                  <p className="text-xs uppercase tracking-wide text-bne-steel">Anomaly review</p>
                  <p className="text-sm text-bne-ink mt-2">
                    Detected: {qualityData.anomalies_detected ?? 0} · Fixed: {qualityData.anomalies_fixed ?? 0}
                  </p>
                  <p className="text-xs text-bne-steel mt-2">
                    Fit for engine: {qualityData.fit_for_engine ? 'Yes' : 'No'}
                  </p>
                </div>
                {(qualityData.warnings || []).length > 0 && (
                  <div className="sm:col-span-2 rounded-lg border border-bne-amber/30 bg-bne-amber/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-amber mb-2">Warnings</p>
                    <ul className="list-disc list-inside text-sm text-bne-ink space-y-1">
                      {qualityData.warnings.map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(qualityData.errors || []).length > 0 && (
                  <div className="sm:col-span-2 rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-crimson mb-2">Errors</p>
                    <ul className="list-disc list-inside text-sm text-bne-crimson space-y-1">
                      {qualityData.errors.map((message, index) => (
                        <li key={index}>{message}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-bne-steel">
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
                  onClick={() => onOpenResults?.(derivedModelId ?? job.id)}
                  disabled={!derivedModelId && !job.id}
                >
                  View model results
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => onOpenModel?.(derivedModelId ?? job.id)}
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
                  <div key={item.label} className="rounded-lg border border-bne-frost bg-bne-ice/40 p-4">
                    <p className="text-xs uppercase tracking-wide text-bne-steel">{item.label}</p>
                    <p className="font-semibold text-bne-ink mt-2">{item.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {job.config && (
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-bne-ice p-4 rounded-lg text-xs font-mono overflow-x-auto">
              {JSON.stringify(job.config, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}

      {job.error && (
        <Card>
          <CardHeader>
            <CardTitle>Error Details</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-bne-crimson/5 border border-bne-crimson/20 rounded-lg p-4">
              <p className="text-sm text-bne-crimson font-mono">{job.error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {job.logs && job.logs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Logs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-bne-ink text-bne-ice p-4 rounded-lg font-mono text-xs overflow-x-auto max-h-96 overflow-y-auto">
              {job.logs.map((log, i) => (
                <div key={i} className="mb-1">
                  <span className="text-bne-steel">[{log.timestamp}]</span>{' '}
                  <span>{log.message}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default function Jobs() {
  const [selectedJobId, setSelectedJobId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)
  const [jobModalDefaults, setJobModalDefaults] = useState(null)
  const { data: jobs, isLoading, error, refetch } = useJobs()
  const navigate = useRouter((state) => state.navigate)

  const filteredJobs = jobs?.filter(job => {
    if (filter === 'all') return true
    if (filter === 'active') return ['pending', 'running'].includes(job.status)
    return job.status === filter
  }) || []

  const jobTypeLookup = useMemo(() => ({
    data_collection: 'Collect, clean, and stage raw datasets.',
    training: 'Fit a predictive model using a completed data collection job.',
    prediction: 'Generate forward-looking risk scores from a trained model.',
    backtest: 'Replay historical periods to validate performance.'
  }), [])

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
        actions={
          <Button variant="primary" onClick={() => setIsJobModalOpen(true)}>
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Job
            </span>
          </Button>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-bne-ink mb-2">What is a job?</h3>
                    <p className="text-sm text-bne-steel leading-relaxed">
                      Jobs are background tasks that move data through Beacon: collecting sources,
                      training models, and running predictions. Track every step here and drill into any failures.
                    </p>
                  </div>
                  <div className="rounded-lg border border-bne-frost bg-bne-ice/40 p-4 text-xs text-bne-steel space-y-2">
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
                Active ({jobs?.filter(j => ['pending', 'running'].includes(j.status)).length || 0})
              </Button>
              <Button
                variant={filter === 'completed' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('completed')}
              >
                Completed ({jobs?.filter(j => j.status === 'completed').length || 0})
              </Button>
              <Button
                variant={filter === 'failed' ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => setFilter('failed')}
              >
                Failed ({jobs?.filter(j => j.status === 'failed').length || 0})
              </Button>
            </div>

            {filteredJobs.length === 0 ? (
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
                      d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <h3 className="text-lg font-semibold text-bne-ink mb-2">No jobs found</h3>
                  <p className="text-sm text-bne-steel">
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
                      key={jobKey}
                      job={job}
                      onSelect={(j) => setSelectedJobId(j.job_id ?? j.id)}
                      isSelected={selectedJobId === jobKey}
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
                onOpenModel={(modelId) => navigate('results', { modelId })}
                onOpenResults={(modelId) => navigate('results', { modelId })}
                onCreateTraining={(dataJob) => {
                  setJobModalDefaults({
                    jobType: 'training',
                    dataJobId: dataJob.id ?? dataJob.job_id
                  })
                  setIsJobModalOpen(true)
                }}
              />
            ) : (
              <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
                <div className="text-center py-12">
                  <svg
                    className="w-12 h-12 mx-auto text-bne-steel/50 mb-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <p className="text-sm text-bne-steel">
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
