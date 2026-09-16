import { useMemo, useState, type ReactNode } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, type CardAccent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Sparkline from '../components/ui/Sparkline'
import { useJobs, useModels, useDataSources, useSystemStatus } from '../hooks/useApi'
import { useDataQualityStats } from '../hooks/useDataQuality'
import JobCreationModal from '../components/jobs/JobCreationModal'
import FirstRunChecklist from '../components/FirstRunChecklist'
import type { Job } from '../types/api'

const DAY_MS = 86_400_000

function relativeTime(date?: string | null): string {
  if (!date) return '—'
  const diff = Date.now() - new Date(date).getTime()
  const minutes = Math.round(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-bne-paper-dim ${className || ''}`} />
}

interface StatCardProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  children?: ReactNode
  accent?: CardAccent | null
}

function StatCard({ label, value, sub, children, accent }: StatCardProps) {
  return (
    <Card accent={accent} className="relative">
      <p className="bne-micro mb-2">{label}</p>
      <p className="font-display text-[30px] font-semibold leading-none tnum text-bne-ink">{value}</p>
      {sub && <p className="mt-2 text-xs text-bne-muted">{sub}</p>}
      {children && <div className="mt-3">{children}</div>}
    </Card>
  )
}

interface MeterProps {
  percent: number
  tone?: 'clay' | 'ochre' | 'moss'
}

function Meter({ percent, tone }: MeterProps) {
  const colour = tone === 'clay' ? 'bg-bne-clay' : tone === 'ochre' ? 'bg-bne-ochre' : 'bg-bne-moss'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-[2px] bg-bne-paper-dim">
      <div className={`h-full ${colour} rounded-[2px] transition-all duration-500`} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  )
}

function JobActivityChart({ jobs }: { jobs: Job[] }) {
  const days = 14
  const buckets = useMemo(() => {
    const now = new Date()
    now.setHours(23, 59, 59, 999)
    const series = Array.from({ length: days }, (_, index) => {
      const dayStart = new Date(now.getTime() - (days - 1 - index) * DAY_MS)
      dayStart.setHours(0, 0, 0, 0)
      const dayEnd = new Date(dayStart.getTime() + DAY_MS)
      const inDay = (jobs || []).filter((job) => {
        const created = job.created_at ? new Date(job.created_at) : null
        return created && created >= dayStart && created < dayEnd
      })
      return {
        label: dayStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        completed: inDay.filter((j) => j.status === 'completed').length,
        running: inDay.filter((j) => j.status === 'running' || j.status === 'pending').length,
        failed: inDay.filter((j) => j.status === 'failed').length
      }
    })
    return series
  }, [jobs])

  const max = Math.max(1, ...buckets.map((b) => b.completed + b.running + b.failed))
  const width = 100 / days

  return (
    <div>
      <svg viewBox="0 0 100 40" className="h-28 w-full" preserveAspectRatio="none" role="img" aria-label="Job activity, last 14 days">
        {buckets.map((bucket, index) => {
          const total = bucket.completed + bucket.running + bucket.failed
          const hf = (bucket.failed / max) * 34
          const hr = (bucket.running / max) * 34
          const hc = (bucket.completed / max) * 34
          const x = index * width + width * 0.18
          const w = width * 0.64
          return (
            <g key={bucket.label}>
              <title>{`${bucket.label}: ${bucket.completed} completed, ${bucket.running} active, ${bucket.failed} failed`}</title>
              <rect x={x} y={40 - hc} width={w} height={Math.max(hc, 0)} fill="#55703B" opacity="0.85" />
              <rect x={x} y={40 - hc - hr} width={w} height={Math.max(hr, 0)} fill="#2C5545" opacity="0.85" />
              <rect x={x} y={40 - hc - hr - hf} width={w} height={Math.max(hf, 0)} fill="#A33D22" opacity="0.9" />
              {total === 0 && <rect x={x} y={39} width={w} height={1} fill="#CFC3A9" />}
            </g>
          )
        })}
        <line x1="0" y1="40" x2="100" y2="40" stroke="#CFC3A9" strokeWidth="0.4" />
      </svg>
      <div className="mt-2 flex items-center gap-4 text-[10px] text-bne-muted">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-bne-moss" /> completed</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-bne-pine" /> active</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-bne-clay" /> failed</span>
        <span className="ml-auto tnum">last {days} days</span>
      </div>
    </div>
  )
}

function SystemStatusCard() {
  const { data, isLoading, isError } = useSystemStatus()

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>System Status</CardTitle>
          {isError ? (
            <Badge variant="danger" size="sm">Unreachable</Badge>
          ) : isLoading ? (
            <Badge size="sm">Checking…</Badge>
          ) : (
            <Badge variant="success" size="sm">{data?.status === 'operational' ? 'Operational' : 'Reported'}</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isError ? (
          <EmptyState compact title="Backend not reachable" hint="Host metrics appear once the API answers; nothing is asserted until then." />
        ) : isLoading || !data ? (
          <div className="space-y-3"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-2/3" /></div>
        ) : (
          <div className="space-y-3.5">
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[13px] text-bne-muted">CPU</span>
                <span className="bne-figure text-[13px]">{data.cpu?.usage_percent?.toFixed(0)}%{data.cpu?.cores ? ` · ${data.cpu.cores} cores` : ''}</span>
              </div>
              <Meter percent={data.cpu?.usage_percent ?? 0} tone={(data.cpu?.usage_percent ?? 0) > 85 ? 'clay' : undefined} />
            </div>
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[13px] text-bne-muted">Memory</span>
                <span className="bne-figure text-[13px]">{data.memory?.usage_percent?.toFixed(0)}%{data.memory ? ` · ${data.memory.used_gb}/${data.memory.total_gb} GB` : ''}</span>
              </div>
              <Meter percent={data.memory?.usage_percent ?? 0} tone={(data.memory?.usage_percent ?? 0) > 85 ? 'clay' : undefined} />
            </div>
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[13px] text-bne-muted">Disk</span>
                <span className="bne-figure text-[13px]">{data.disk?.usage_percent?.toFixed(0)}%{data.disk ? ` · ${data.disk.used_gb}/${data.disk.total_gb} GB` : ''}</span>
              </div>
              <Meter percent={data.disk?.usage_percent ?? 0} tone={(data.disk?.usage_percent ?? 0) > 85 ? 'ochre' : undefined} />
            </div>
            <div className="flex items-center justify-between border-t border-bne-line-soft pt-2">
              <span className="text-[13px] text-bne-muted">GPU</span>
              {data.gpu?.available ? (
                <Badge variant="primary" size="sm">{data.gpu.count} device{(data.gpu.count ?? 0) > 1 ? 's' : ''}</Badge>
              ) : (
                <Badge size="sm">Not available</Badge>
              )}
            </div>
            {data.version && (
              <p className="bne-micro text-[9px] text-bne-faint">backend v{data.version} · {String(data.git_revision).slice(0, 7)}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DataQualityCard() {
  const { data, isLoading, isError } = useDataQualityStats()

  return (
    <Card>
      <CardHeader>
        <CardTitle>Data Quality</CardTitle>
      </CardHeader>
      <CardContent>
        {isError ? (
          <EmptyState compact title="No quality report yet" hint="Run a data collection job to certify sources." />
        ) : isLoading || !data ? (
          <div className="space-y-3"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-3/4" /></div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-[13px] text-bne-muted">Overall health</span>
              <span className="font-display text-xl font-semibold tnum">{data.overview?.overall_health ?? '—'}%</span>
            </div>
            <Meter percent={data.overview?.overall_health ?? 0} tone={(data.overview?.overall_health ?? 0) < 60 ? 'ochre' : undefined} />
            <div>
              <p className="bne-micro mb-1.5">Freshness</p>
              <div className="flex h-2 w-full overflow-hidden rounded-[2px] bg-bne-paper-dim">
                {data.freshness && (
                  <>
                    <div className="h-full bg-bne-moss" style={{ width: `${(data.freshness.fresh / Math.max(1, data.freshness.fresh + data.freshness.stale + data.freshness.outdated + data.freshness.never_synced)) * 100}%` }} />
                    <div className="h-full bg-bne-ochre" style={{ width: `${(data.freshness.stale / Math.max(1, data.freshness.fresh + data.freshness.stale + data.freshness.outdated + data.freshness.never_synced)) * 100}%` }} />
                    <div className="h-full bg-bne-clay" style={{ width: `${(data.freshness.outdated / Math.max(1, data.freshness.fresh + data.freshness.stale + data.freshness.outdated + data.freshness.never_synced)) * 100}%` }} />
                    <div className="h-full bg-bne-stone" style={{ width: `${(data.freshness.never_synced / Math.max(1, data.freshness.fresh + data.freshness.stale + data.freshness.outdated + data.freshness.never_synced)) * 100}%` }} />
                  </>
                )}
              </div>
              <div className="mt-1.5 flex justify-between text-[10px] text-bne-muted tnum">
                <span>{data.freshness?.fresh ?? 0} fresh</span>
                <span>{data.freshness?.stale ?? 0} stale</span>
                <span>{data.freshness?.outdated ?? 0} outdated</span>
                <span>{data.freshness?.never_synced ?? 0} never synced</span>
              </div>
            </div>
            <div className="flex items-center justify-between border-t border-bne-line-soft pt-2">
              <span className="text-[13px] text-bne-muted">Anomalies detected</span>
              <span className="bne-figure text-[13px]">
                {(data.anomalies?.low_quality_jobs ?? 0) + (data.anomalies?.error_sources ?? 0) + (data.anomalies?.recent_failures ?? 0)}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const [isJobModalOpen, setIsJobModalOpen] = useState(false)
  const { data: jobs, isLoading: jobsLoading, isError: jobsError } = useJobs()
  const { data: models, isLoading: modelsLoading } = useModels()
  const { data: dataSources, isLoading: sourcesLoading } = useDataSources()

  const stats = useMemo(() => {
    const list = Array.isArray(jobs) ? jobs : []
    const completed = list.filter((j) => j.status === 'completed').length
    const running = list.filter((j) => j.status === 'running' || j.status === 'pending').length
    const perDay = Array.from({ length: 14 }, (_, index) => {
      const start = new Date(Date.now() - (13 - index) * DAY_MS)
      start.setHours(0, 0, 0, 0)
      const end = new Date(start.getTime() + DAY_MS)
      return list.filter((j) => j.created_at && new Date(j.created_at) >= start && new Date(j.created_at) < end).length
    })
    return {
      total: list.length,
      completed,
      running,
      rate: list.length ? Math.round((completed / list.length) * 100) : null,
      perDay
    }
  }, [jobs])

  const modelList = Array.isArray(models) ? models : []
  // The catalogue lists completed training jobs; 'active'/'ready' are statuses
  // the endpoint never emits, so this count used to be permanently 0.
  const activeModels = modelList.filter((m) => m.status === 'completed').length
  const sourceList = Array.isArray(dataSources) ? dataSources : []
  const enabledSources = sourceList.filter((s) => s.enabled).length

  const recentJobs = (Array.isArray(jobs) ? jobs : []).slice(0, 6)

  return (
    <>
      <PageContainer
        eyebrow="Operations"
        title="Dashboard"
        subtitle="Collection, training and scoring activity across the platform, with live host and data-quality state."
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
        <div className="space-y-5">
          <FirstRunChecklist />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {jobsLoading ? (
              <Card><Skeleton className="h-16 w-full" /></Card>
            ) : jobsError ? (
              <StatCard label="Jobs" value="—" sub="Job service not reachable">
                <EmptyState compact title="No job history" hint="Jobs appear here once the queue accepts work." />
              </StatCard>
            ) : (
              <StatCard label="Total Jobs" value={stats.total} sub={`${stats.running} active now`} accent="pine">
                <Sparkline values={stats.perDay} ariaLabel="jobs per day, last 14 days" />
              </StatCard>
            )}
            <StatCard
              label="Completion Rate"
              value={stats.rate === null ? '—' : `${stats.rate}%`}
              sub={`${stats.completed} of ${stats.total} completed`}
            >
              <Meter percent={stats.rate ?? 0} tone={(stats.rate ?? 0) < 60 ? 'ochre' : undefined} />
            </StatCard>
            {modelsLoading ? (
              <Card><Skeleton className="h-16 w-full" /></Card>
            ) : (
              <StatCard label="Active Models" value={activeModels} sub={`of ${modelList.length} registered`} />
            )}
            {sourcesLoading ? (
              <Card><Skeleton className="h-16 w-full" /></Card>
            ) : (
              <StatCard label="Data Sources" value={enabledSources} sub={`of ${sourceList.length} configured`} />
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Job Activity</CardTitle>
                  <Button variant="ghost" size="sm">View All</Button>
                </div>
              </CardHeader>
              <CardContent>
                {jobsLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : !Array.isArray(jobs) || jobs.length === 0 ? (
                  <EmptyState
                    title="No jobs yet"
                    hint="Create a data-collection job to certify sources, then train and score. Every run is gated by the data-quality attestation."
                    action={<Button variant="secondary" size="sm" onClick={() => setIsJobModalOpen(true)}>Create the first job</Button>}
                  />
                ) : (
                  <JobActivityChart jobs={jobs} />
                )}
              </CardContent>
              {recentJobs.length > 0 && (
                <CardContent className="border-t border-bne-line-soft pt-3">
                  <div className="space-y-2">
                    {recentJobs.map((job) => {
                      const jobKey = job.job_id ?? job.id
                      return (
                        <div key={String(jobKey)} className="flex items-center justify-between rounded-md border border-bne-line-soft bg-bne-paper-raise px-3 py-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-bne-ink">{job.job_type}</p>
                            <p className="font-mono text-[10px] text-bne-faint tnum">#{String(jobKey)} · {relativeTime(job.created_at)}</p>
                          </div>
                          <Badge
                            variant={
                              job.status === 'completed' ? 'success'
                              : job.status === 'running' ? 'primary'
                              : job.status === 'failed' ? 'danger'
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
                </CardContent>
              )}
            </Card>

            <div className="space-y-4">
              <SystemStatusCard />
              <DataQualityCard />
              <Card>
                <CardHeader>
                  <CardTitle>Quick Actions</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 gap-2">
                  <Button variant="secondary" size="sm" onClick={() => setIsJobModalOpen(true)}>Collect data</Button>
                  <Button variant="ghost" size="sm" onClick={() => setIsJobModalOpen(true)}>Train & score</Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </PageContainer>
      <JobCreationModal isOpen={isJobModalOpen} onClose={() => setIsJobModalOpen(false)} />
    </>
  )
}
