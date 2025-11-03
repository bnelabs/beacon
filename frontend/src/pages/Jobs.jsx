import { useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useJobs, useJob, useCancelJob } from '../hooks/useApi'

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
      cancelMutation.mutate(job.job_id)
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
          <p className="text-sm text-bne-steel font-mono">ID: {job.job_id}</p>
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

function JobDetails({ jobId }) {
  const { data: job, isLoading, error } = useJob(jobId)

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
              <p className="font-mono text-sm text-bne-ink mt-1">{job.job_id}</p>
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
  const { data: jobs, isLoading, error, refetch } = useJobs()

  const filteredJobs = jobs?.filter(job => {
    if (filter === 'all') return true
    if (filter === 'active') return ['pending', 'running'].includes(job.status)
    return job.status === filter
  }) || []

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
    <PageContainer
      title="Jobs"
      actions={
        <Button variant="primary">
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
              {filteredJobs.map((job) => (
                <JobRow
                  key={job.job_id}
                  job={job}
                  onSelect={(j) => setSelectedJobId(j.job_id)}
                  isSelected={selectedJobId === job.job_id}
                />
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-1">
          {selectedJobId ? (
            <JobDetails jobId={selectedJobId} />
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
  )
}
