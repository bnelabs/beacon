import { useEffect, useMemo, useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import { cn } from '../utils/cn'
import { useDataSources, useSystemStatus } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'

const PREFERENCES_KEY = 'beacon.preferences.v1'

/** Browser-local UI preferences. BEACON has no accounts; these never leave
 *  this device and are labelled as local wherever they surface. */
interface Preferences {
  emailAlerts: boolean
  jobLifecycle: boolean
  weeklyDigest: boolean
  autoRefresh: boolean
  confirmBeforeStop: boolean
  experimentalFeatures: boolean
}

const DEFAULT_PREFERENCES: Preferences = {
  emailAlerts: true,
  jobLifecycle: true,
  weeklyDigest: false,
  autoRefresh: true,
  confirmBeforeStop: true,
  experimentalFeatures: false
}

function loadPreferences(): Preferences {
  try {
    const raw = window.localStorage.getItem(PREFERENCES_KEY)
    if (!raw) return DEFAULT_PREFERENCES
    return { ...DEFAULT_PREFERENCES, ...(JSON.parse(raw) as Partial<Preferences>) }
  } catch {
    return DEFAULT_PREFERENCES
  }
}

interface PreferenceToggleProps {
  label: string
  description?: string
  value: boolean
  onChange: () => void
}

function PreferenceToggle({ label, description, value, onChange }: PreferenceToggleProps) {
  return (
    <button
      type="button"
      onClick={onChange}
      className="w-full flex items-center justify-between gap-6 rounded-md border border-bne-line px-4 py-3 text-left transition-colors hover:border-bne-pine hover:bg-bne-pine/5 focus:outline-none focus:ring-2 focus:ring-bne-pine"
    >
      <span>
        <span className="block text-sm font-semibold text-bne-ink">{label}</span>
        {description && <span className="mt-1 block text-xs text-bne-muted">{description}</span>}
      </span>
      <span
        className={cn(
          'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
          value ? 'bg-bne-pine' : 'bg-bne-paper-dim'
        )}
      >
        <span
          className={cn(
            'inline-block h-4 w-4 transform rounded-full bg-bne-card shadow transition-transform',
            value ? 'translate-x-5' : 'translate-x-1'
          )}
        />
      </span>
    </button>
  )
}

/** The provider plugins the credentials card reports on. Rows are rendered
 *  from what is actually configured under Data Sources — no feed is claimed
 *  as connected that the registry does not report. */
const TRACKED_FEEDS: Array<{ name: string; pluginType: string; blurb: string }> = [
  { name: 'FRED', pluginType: 'fred', blurb: 'Federal Reserve Economic Data API' },
  { name: 'Alpha Vantage', pluginType: 'alpha_vantage', blurb: 'Equities and FX tick-level signals' },
  { name: 'SEC Filings', pluginType: 'sec', blurb: 'EDGAR corporate disclosure feed' }
]

export default function Settings() {
  const { data: systemStatus } = useSystemStatus()
  const { data: feedSources } = useDataSources()
  const navigate = useRouter((state) => state.navigate)
  const [preferences, setPreferences] = useState<Preferences>(loadPreferences)

  const feedStatus = (pluginType: string) => {
    const match = (feedSources ?? []).find((source) => source.plugin_type === pluginType)
    if (!match) return { label: 'Not configured', configured: false, enabled: false }
    return {
      label: match.enabled ? 'Connected' : 'Configured · disabled',
      configured: true,
      enabled: Boolean(match.enabled)
    }
  }

  // Preferences are UI-side state: persisted in this browser, and labelled as
  // such. Nothing here pretends to be a server-side account setting while
  // BEACON ships without authentication.
  useEffect(() => {
    try {
      window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(preferences))
    } catch {
      // private mode / storage disabled: settings stay session-only
    }
  }, [preferences])

  const toggles = useMemo<Array<{ key: keyof Preferences; label: string; description: string }>>(
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

  const workspaceToggles = useMemo<Array<{ key: keyof Preferences; label: string; description: string }>>(
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

  const handleToggle = (key: keyof Preferences) => {
    setPreferences((previous) => ({
      ...previous,
      [key]: !previous[key]
    }))
  }

  const platformVersion = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown'

  return (
    <PageContainer title="Settings" className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Platform</CardTitle>
            <Badge variant="primary" size="sm">v{platformVersion}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-[13px] text-bne-muted">
          <div className="flex justify-between"><span>Build channel</span><span className="bne-figure">{import.meta.env.MODE}</span></div>
          <div className="flex justify-between">
            <span>Backend</span>
            <span className="bne-figure">
              {systemStatus?.version ? `v${systemStatus.version} · ${String(systemStatus.git_revision || '').slice(0, 7)}` : 'not reachable'}
            </span>
          </div>
          <div className="flex justify-between"><span>Preferences storage</span><span>this browser (localStorage)</span></div>
          <div className="flex justify-between">
            <span>Authentication</span>
            <span>
              {!systemStatus
                ? 'not reachable'
                : systemStatus.auth?.mode === 'bearer-gate'
                  ? 'bearer gate — token required on /api/*'
                  : 'not configured — single-operator mode'}
            </span>
          </div>
        </CardContent>
      </Card>

      <p className="text-sm text-bne-muted">
        Preferences are stored in this browser only. BEACON has no user accounts,
        roles or per-user state: a deployment either runs open on a trusted
        network or gates every <span className="bne-figure">/api/*</span> call
        behind one shared bearer token (<span className="bne-figure">BEACON_API_TOKEN</span>),
        which the posture above reports live from the backend.
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
            <Button variant="ghost" size="sm" onClick={() => setPreferences({ ...DEFAULT_PREFERENCES, emailAlerts: false, jobLifecycle: false, weeklyDigest: false })}>
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

      <Card>
        <CardHeader>
          <CardTitle>Linked data feeds</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-bne-muted">
          {/* Live state, read from the configured sources — the previous card
              printed a static "Connected" badge for FRED and dead "Connect"
              buttons for the others: invented states of exactly the kind the
              platform refuses everywhere else. There is no OAuth flow here;
              connecting a feed means configuring the source, so that is where
              the button goes. (The "Team access" card that sat beside this
              one promised roles and invites on a product whose own copy says
              it has no user accounts; it is gone rather than honest-labelled,
              because there is nothing true left to say in it.) */}
          {TRACKED_FEEDS.map((feed) => {
            const status = feedStatus(feed.pluginType)
            return (
              <div key={feed.pluginType} className="flex items-center justify-between rounded-md border border-bne-line px-4 py-3">
                <div>
                  <p className="font-semibold text-bne-ink">{feed.name}</p>
                  <p className="text-xs text-bne-muted">{feed.blurb}</p>
                </div>
                <div className="flex items-center gap-3">
                  {status.configured ? (
                    <span
                      className={cn(
                        'rounded-full px-3 py-1 text-xs font-semibold',
                        status.enabled ? 'bg-bne-moss/10 text-bne-moss' : 'bg-bne-paper-dim text-bne-muted'
                      )}
                    >
                      {status.label}
                    </span>
                  ) : (
                    <span className="rounded-full bg-bne-paper-dim px-3 py-1 text-xs font-semibold text-bne-muted">
                      {status.label}
                    </span>
                  )}
                  <Button variant="outline" size="sm" onClick={() => navigate('datasources')}>
                    {status.configured ? 'Manage' : 'Add in Data Sources'}
                  </Button>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </PageContainer>
  )
}
