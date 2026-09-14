import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'

const knowledgeBaseArticles = [
  {
    title: 'Connecting data sources',
    blurb: 'Bring in central bank, balance sheet, and transaction datasets so Beacon can orchestrate pipelines end-to-end.'
  },
  {
    title: 'Training risk models',
    blurb: 'Walk through building your first credit risk scenario model, including feature engineering templates.'
  },
  {
    title: 'Reading simulation results',
    blurb: 'Learn how Beacon scores contagion paths and how to interpret stress-test outputs with stakeholders.'
  }
]

export default function Help() {
  return (
    <PageContainer title="Help Center" className="space-y-6">
      <p className="text-sm text-bne-muted">
        Explore guides, best practices, and support options for the Beacon banking network engine. Everything here is kept concise so you can keep momentum while investigating portfolios.
      </p>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Popular walkthroughs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {knowledgeBaseArticles.map((article) => (
              <div key={article.title} className="rounded-md border border-bne-line px-4 py-3">
                <h3 className="text-sm font-semibold text-bne-ink">{article.title}</h3>
                <p className="mt-2 text-xs text-bne-muted">{article.blurb}</p>
                <a
                  href="https://docs.usebeacon.ai"
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-bne-pine hover:underline"
                >
                  Open guide
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5h10M19 5v10m0-10L5 19" />
                  </svg>
                </a>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-bne-muted">
            <div className="flex items-center justify-between rounded-md border border-bne-line px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-bne-ink">Beacon Cloud</p>
                <p className="text-xs text-bne-muted">API latency and job execution queues</p>
              </div>
              <span className="rounded-full bg-bne-moss/10 px-3 py-1 text-xs font-semibold text-bne-moss">Operational</span>
            </div>
            <p>
              Incident history and uptime reports are available at{' '}
              <a href="https://status.usebeacon.ai" target="_blank" rel="noreferrer" className="font-medium text-bne-pine hover:underline">
                status.usebeacon.ai
              </a>.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Need more help?</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3 text-sm text-bne-muted">
          <div className="rounded-md border border-bne-line p-4">
            <p className="text-sm font-semibold text-bne-ink">Ask Beacon Support</p>
            <p className="mt-2 text-xs text-bne-muted">Weekdays 8:00&ndash;18:00 GMT</p>
            <a href="mailto:support@usebeacon.ai" className="mt-3 inline-flex text-sm font-medium text-bne-pine hover:underline">
              support@usebeacon.ai
            </a>
          </div>
          <div className="rounded-md border border-bne-line p-4">
            <p className="text-sm font-semibold text-bne-ink">Join the community</p>
            <p className="mt-2 text-xs text-bne-muted">Share strategies and learn from other risk teams.</p>
            <a href="https://community.usebeacon.ai" target="_blank" rel="noreferrer" className="mt-3 inline-flex text-sm font-medium text-bne-pine hover:underline">
              Community hub
            </a>
          </div>
          <div className="rounded-md border border-bne-line p-4">
            <p className="text-sm font-semibold text-bne-ink">Schedule a workshop</p>
            <p className="mt-2 text-xs text-bne-muted">Hands-on sessions to review models, data gaps, and governance.</p>
            <a href="https://cal.usebeacon.ai" target="_blank" rel="noreferrer" className="mt-3 inline-flex text-sm font-medium text-bne-pine hover:underline">
              Book time
            </a>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
