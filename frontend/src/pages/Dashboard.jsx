import { useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { useJobs, useModels, useDataSources } from '../hooks/useApi'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import JobCreationModal from '../components/jobs/JobCreationModal'
import WelcomeBanner from '../components/WelcomeBanner'

function StatsCard({ title, value, change, trend }) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-bne-steel mb-1">{title}</p>
          <p className="text-3xl font-semibold text-bne-ink">{value}</p>
          {change && (
            <div className="flex items-center gap-1 mt-2">
              <Badge variant={trend === 'up' ? 'success' : 'danger'} size="sm">
                {trend === 'up' ? '↑' : '↓'} {change}
              </Badge>
              <span className="text-xs text-bne-steel">vs last week</span>
            </div>
          )}
        </div>
      </div>
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
          <p className="text-sm text-bne-steel text-center py-4">No jobs yet</p>
        ) : (
          <div className="space-y-3">
            {recentJobs.map((job) => {
              const jobKey = job.job_id ?? job.id
              return (
                <div
                  key={jobKey}
                  className="flex items-center justify-between p-3 rounded-lg bg-bne-ice hover:bg-bne-frost transition-colors"
                >
                  <div className="flex-1">
                    <p className="text-sm font-medium text-bne-ink">
                      {job.model_id || 'Unknown Model'}
                    </p>
                    <p className="text-xs text-bne-steel mt-0.5">
                      ID: {jobKey ?? '-'}
                    </p>
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

  const stats = {
    totalJobs: jobs?.length || 0,
    activeModels: models?.length || 0,
    dataSources: dataSources?.length || 0,
    completionRate: jobs?.length > 0
      ? Math.round((jobs.filter(j => j.status === 'completed').length / jobs.length) * 100)
      : 0
  }

  return (
    <>
      <PageContainer
        title="Dashboard"
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
      <div className="space-y-6">
        <WelcomeBanner />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatsCard
            title="Total Jobs"
            value={stats.totalJobs}
            change="12%"
            trend="up"
          />
          <StatsCard
            title="Active Models"
            value={stats.activeModels}
          />
          <StatsCard
            title="Data Sources"
            value={stats.dataSources}
          />
          <StatsCard
            title="Completion Rate"
            value={`${stats.completionRate}%`}
            change="5%"
            trend="up"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <RecentJobs
            jobs={jobs}
            isLoading={jobsLoading}
            error={jobsError}
          />

          <Card>
            <CardHeader>
              <CardTitle>System Status</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-bne-steel">API Status</span>
                  <Badge variant="success" size="sm">Operational</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-bne-steel">Database</span>
                  <Badge variant="success" size="sm">Connected</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-bne-steel">Cache</span>
                  <Badge variant="success" size="sm">Active</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-bne-steel">Workers</span>
                  <Badge variant="primary" size="sm">2 Active</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Button variant="outline" className="h-24 flex flex-col items-center justify-center gap-2">
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-sm font-medium">View Globe</span>
              </Button>
              <Button variant="outline" className="h-24 flex flex-col items-center justify-center gap-2">
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <span className="text-sm font-medium">Train Model</span>
              </Button>
              <Button variant="outline" className="h-24 flex flex-col items-center justify-center gap-2">
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
