import { useMemo, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import { cn } from '../utils/cn'
import { useOnboarding } from '../hooks/useOnboarding'

function PreferenceToggle({ label, description, value, onChange }) {
  return (
    <button
      type="button"
      onClick={onChange}
      className="w-full flex items-center justify-between gap-6 rounded-xl border border-bne-frost px-4 py-3 text-left transition-colors hover:border-bne-azure hover:bg-bne-azure/5 focus:outline-none focus:ring-2 focus:ring-bne-azure"
    >
      <span>
        <span className="block text-sm font-semibold text-bne-ink">{label}</span>
        {description && <span className="mt-1 block text-xs text-bne-steel">{description}</span>}
      </span>
      <span
        className={cn(
          'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
          value ? 'bg-bne-azure' : 'bg-bne-frost'
        )}
      >
        <span
          className={cn(
            'inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform',
            value ? 'translate-x-5' : 'translate-x-1'
          )}
        />
      </span>
    </button>
  )
}

export default function Settings() {
  const { hasCompletedOnboarding, startOnboarding, resetOnboarding } = useOnboarding()
  const [preferences, setPreferences] = useState({
    emailAlerts: true,
    jobLifecycle: true,
    weeklyDigest: false,
    autoRefresh: true,
    confirmBeforeStop: true,
    experimentalFeatures: false
  })

  const toggles = useMemo(
    () => [
      {
        key: 'emailAlerts',
        label: 'Daily email alerts',
        description: 'Receive a morning summary when new datasets or anomaly alerts are available.'
      },
      {
        key: 'jobLifecycle',
        label: 'Job lifecycle updates',
        description: 'Notify me when training jobs start, finish, or require manual action.'
      },
      {
        key: 'weeklyDigest',
        label: 'Weekly portfolio digest',
        description: 'Compilation of top signals, sector rotations, and data quality issues every Friday.'
      }
    ],
    []
  )

  const workspaceToggles = useMemo(
    () => [
      {
        key: 'autoRefresh',
        label: 'Auto-refresh dashboards',
        description: 'Keep dashboard widgets live with background refresh every 60 seconds.'
      },
      {
        key: 'confirmBeforeStop',
        label: 'Confirm before stopping jobs',
        description: 'Avoid accidental cancellations by asking for confirmation when stopping a job early.'
      },
      {
        key: 'experimentalFeatures',
        label: 'Enable experimental features',
        description: 'Preview upcoming Beacon capabilities before they are generally available.'
      }
    ],
    []
  )

  const handleToggle = (key) => {
    setPreferences((previous) => ({
      ...previous,
      [key]: !previous[key]
    }))
  }

  return (
    <PageContainer title="Settings" className="space-y-6">
      <p className="text-sm text-bne-steel">
        Personalise how Beacon keeps you informed. Settings are stored locally while role-based policies remain managed by your administrator.
      </p>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Notification preferences</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {toggles.map((toggle) => (
              <PreferenceToggle
                key={toggle.key}
                label={toggle.label}
                description={toggle.description}
                value={preferences[toggle.key]}
                onChange={() => handleToggle(toggle.key)}
              />
            ))}
          </CardContent>
          <CardFooter className="justify-end">
            <Button variant="ghost" size="sm" onClick={() => setPreferences((prev) => ({ ...prev, emailAlerts: false, jobLifecycle: false, weeklyDigest: false }))}>
              Mute all
            </Button>
            <Button variant="primary" size="sm" disabled>
              Saved locally
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Workspace defaults</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {workspaceToggles.map((toggle) => (
              <PreferenceToggle
                key={toggle.key}
                label={toggle.label}
                description={toggle.description}
                value={preferences[toggle.key]}
                onChange={() => handleToggle(toggle.key)}
              />
            ))}
          </CardContent>
          <CardFooter className="justify-end">
            <Button variant="ghost" size="sm" onClick={() => setPreferences((prev) => ({ ...prev, autoRefresh: false, confirmBeforeStop: true, experimentalFeatures: false }))}>
              Restore defaults
            </Button>
          </CardFooter>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Linked data credentials</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-bne-steel">
            <div className="flex items-center justify-between rounded-xl border border-bne-frost px-4 py-3">
              <div>
                <p className="font-semibold text-bne-ink">FRED</p>
                <p className="text-xs text-bne-steel">Federal Reserve Economic Data API</p>
              </div>
              <span className="rounded-full bg-bne-emerald/10 px-3 py-1 text-xs font-semibold text-bne-emerald">Connected</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-bne-frost px-4 py-3">
              <div>
                <p className="font-semibold text-bne-ink">Alpha Vantage</p>
                <p className="text-xs text-bne-steel">Equities and FX tick-level signals</p>
              </div>
              <Button variant="outline" size="sm">Connect</Button>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-bne-frost px-4 py-3">
              <div>
                <p className="font-semibold text-bne-ink">SEC Filings</p>
                <p className="text-xs text-bne-steel">EDGAR corporate disclosure feed</p>
              </div>
              <Button variant="outline" size="sm">Connect</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Team access</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-bne-steel">
            <p>Beacon is currently configured with a single workspace role (<span className="font-medium text-bne-ink">Administrator</span>). Role-based access control will arrive in the next release.</p>
            <div className="rounded-xl border border-bne-frost px-4 py-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-bne-ink">You</span>
                <span className="text-xs font-semibold rounded-full bg-bne-azure/10 text-bne-azure px-2 py-1">Owner</span>
              </div>
              <p className="text-xs text-bne-steel">Invite teammates once directory sync is enabled for your organisation.</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-bne-azure/30 bg-gradient-to-br from-bne-azure/5 to-bne-indigo/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <svg className="w-5 h-5 text-bne-azure" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
            Getting Started
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-gradient-to-br from-bne-azure to-bne-indigo flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-bne-ink mb-1">Interactive Tour</h4>
              <p className="text-sm text-bne-steel mb-3">
                {hasCompletedOnboarding
                  ? "Want to review the basics? Restart the guided tour to explore BEACON's key features again."
                  : "New to BEACON? Take a quick tour to learn about the platform's key features and capabilities."}
              </p>
              <Button
                variant="primary"
                size="sm"
                onClick={startOnboarding}
              >
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {hasCompletedOnboarding ? 'Restart Tour' : 'Start Tour'}
              </Button>
            </div>
          </div>

          <div className="pt-4 border-t border-bne-frost/50">
            <div className="flex items-start gap-3 text-sm">
              <svg className="w-5 h-5 text-bne-steel flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <p className="text-bne-steel">
                  Press <kbd className="px-2 py-1 mx-1 text-xs font-mono bg-white rounded border border-bne-frost">⌘K</kbd> anytime to open global search.
                  Navigate to the <span className="font-medium text-bne-ink">Help Center</span> for detailed documentation.
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
