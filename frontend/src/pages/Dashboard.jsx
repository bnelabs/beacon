import { useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { useJobs, useModels, useDataSources, useSystemStatus } from '../hooks/useApi'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import JobCreationModal from '../components/jobs/JobCreationModal'
import WelcomeBanner from '../components/WelcomeBanner'

function StatsCard({ title, value, accent }) {
  return (
    <Card accent={accent}>
      <p className="bne-micro mb-2">{title}</p>
      <p className="font-display text-[32px] font-semibold leading-none tnum text-bne-ink">
        {value}
      </p>
    </Card>
  )
}

function Meter({ label, percent, detail }) {
  // Band thresholds are presentation only: they colour a measured value,
  // they do not classify risk.
  const tone =
    percent >= 90 ? 'bg-bne-clay' : percent >= 70 ? 'bg-bne-ochre' : 'bg-bne-moss'
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[13px] text-bne-muted">{label}</span>
        <span className="bne-figure text-[13px] tnum">
          {percent.toFixed(0)}%
          {detail && <span className="text-bne-faint font-sans"> · {detail}</span>}
        </span>
      </div>
      <div className="h-1.5 bg-bne-paper-dim rounded-[2px] overflow-hidden">
        <div
          className={`h-full ${tone} rounded-[2px] transition-all duration-500`}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
    </div>
  )
}

function SystemStatus() {
  const { data, isLoading, error, isFetching } = useSystemStatus()

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>System Status</CardTitle>
          {error ? (
            <Badge variant="danger" size="sm">Unreachable</Badge>
          ) : isLoading ? (
            <Badge size="sm">Checking…</Badge>
          ) : (
            <Badge variant="success" size="sm">
              {data?.status === 'operational' ? 'Operational' : 'Reported'}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          // An unreachable backend is reported as unknown, never as green.
          <p className="text-[13px] text-bne-muted">
            The status endpoint did not respond ({String(error.message || error)}).
            Nothing is asserted about system health until it does.
          </p>
        ) : isLoading || !data ? (
          <LoadingSpinner size="sm" message="Reading system status…" />
        ) : (
          <div className="space-y-3.5">
            <Meter
              label="CPU"
              percent={data.cpu?.usage_percent ?? 0}
              detail={data.cpu?.cores ? `${data.cpu.cores} cores` : null}
            />
            <Meter
              label="Memory"
              percent={data.memory?.usage_percent ?? 0}
              detail={
                data.memory
                  ? `${data.memory.used_gb}/${data.memory.total_gb} GB`
                  : null
              }
            />
            <Meter
              label="Disk"
              percent={data.disk?.usage_percent ?? 0}
              detail={data.disk ? `${data.disk.used_gb}/${data.disk.total_gb} GB` : null}
            />
            <div className="flex items-center justify-between pt-1 border-t border-bne-line-soft">
              <span className="text-[13px] text-bne-muted">GPU</span>
              {data.gpu?.available ? (
                <Badge variant="primary" size="sm">
                  {data.gpu.count} device{data.gpu.count > 1 ? 's' : ''}
                </Badge>
              ) : (
                <Badge size="sm">Not available</Badge>
              )}
            </div>
            {isFetching && !isLoading && (
              <p className="bne-micro text-[9px]">Refreshing…</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RecentJobs({ jobs, isLoading, error }) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Jobs</CardTitle>
        </CardHeader>
        <CardContent>
          <LoadingSpinner message="Loading jobs..." />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Jobs</CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorMessage error={error} />
        </CardContent>
      </Card>
    )
  }

  const recentJobs = jobs?.slice(0, 5) || []

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Recent Jobs</CardTitle>
          <Button variant="ghost" size="sm">View All</Button>
        </div>
      </CardHeader>
      <CardContent>
        {recentJobs.length === 0 ? (
          <p className="text-sm text-bne-muted text-center py-4">No jobs yet</p>
        ) : (
          <div className="space-y-2">
            {recentJobs.map((job) => {
              const jobKey = job.job_id ?? job.id
              return (
                <div
                  key={jobKey}
                  className="flex items-center justify-between px-3 py-2.5 rounded-md bg-bne-paper-raise border border-bne-line-soft hover:border-bne-line transition-colors"
                >
                  <div>
                    <p className="text-sm font-medium text-bne-ink">{job.job_type}</p>
                    <p className="text-xs text-bne-faint font-mono tnum">#{jobKey}</p>
                  </div>
                  <Badge
                    variant={
                      job.status === 'completed'
                        ? 'success'
                        : job.status === 'running'
                        ? 'primary'
                        : job.status === 'failed'
                        ? 'danger'
                        : 'default'
                    }
                    size="sm"
                  >
                    {job.status}
                  </Badge>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)
  const { data: jobs, isLoading: jobsLoading, error: jobsError } = useJobs()
  const { data: models, isLoading: modelsLoading } = useModels()
  const { data: dataSources, isLoading: sourcesLoading } = useDataSources()

  const completedJobs = jobs?.filter((j) => j.status === 'completed').length ?? 0
  const stats = {
    totalJobs: jobs?.length || 0,
    activeModels: models?.length || 0,
    dataSources: dataSources?.length || 0,
    // A measured ratio over the jobs that exist — no invented "vs last week"
    // deltas: nothing in the payload compares to a previous period.
    completionRate: jobs?.length > 0
      ? Math.round((completedJobs / jobs.length) * 100)
      : null
  }

  return (
    <>
      <PageContainer
        eyebrow="Operations"
        title="Dashboard"
        subtitle="Collection, training and scoring activity across the platform, with live host status."
        actions={
          <Button variant="primary" onClick={() => setIsJobModalOpen(true)}>
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Job
            </span>
          </Button>
        }
      >
      <div className="space-y-6">
        <WelcomeBanner />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
          <StatsCard title="Total Jobs" value={stats.totalJobs} accent="pine" />
          <StatsCard title="Active Models" value={stats.activeModels} />
          <StatsCard title="Data Sources" value={stats.dataSources} />
          <StatsCard
            title="Completion Rate"
            value={stats.completionRate === null ? '—' : `${stats.completionRate}%`}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <RecentJobs
            jobs={jobs}
            isLoading={jobsLoading}
            error={jobsError}
          />
          <SystemStatus />
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Button variant="secondary" className="h-24 flex flex-col items-center justify-center gap-2 text-bne-ink">
                <svg className="w-7 h-7 text-bne-pine" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span className="text-sm font-medium">View Risk Map</span>
              </Button>
              <Button variant="secondary" className="h-24 flex flex-col items-center justify-center gap-2 text-bne-ink">
                <svg className="w-7 h-7 text-bne-pine" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <span className="text-sm font-medium">Train Model</span>
              </Button>
              <Button variant="secondary" className="h-24 flex flex-col items-center justify-center gap-2 text-bne-ink">
                <svg className="w-7 h-7 text-bne-pine" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="text-sm font-medium">View Results</span>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
      </PageContainer>
      <JobCreationModal
        isOpen={isJobModalOpen}
        onClose={() => setIsJobModalOpen(false)}
      />
    </>
  )
}
