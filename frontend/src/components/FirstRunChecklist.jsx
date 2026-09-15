import { useState } from 'react'
import Card from './ui/Card'
import Button from './ui/Button'
import { useDataSources } from '../hooks/useApi'
import { useDataSourceHealth } from '../hooks/useApi'
import { useNetworkGraph } from '../hooks/useApi'
import { useRouter } from '../store/useRouter'

const STORAGE_KEY = 'beacon-checklist-dismissed'

/**
 * The successor to the guided tour, and deliberately not a tour.
 *
 * why: a scripted walkthrough describes the product the author had, at the
 * moment they wrote it. These steps are derived from live state instead --
 * no sources configured, nothing fetched yet, nothing on a schedule, no
 * exposure matrix -- so each one is true when it appears and disappears the
 * moment the underlying state clears. A step can also be dismissed by hand;
 * dismissals live in localStorage and never come back on their own.
 */
export default function FirstRunChecklist() {
  const { navigate } = useRouter()
  const { data: sources } = useDataSources()
  const { data: healthPayload } = useDataSourceHealth()
  const { data: networkPayload } = useNetworkGraph()
  const [dismissed, setDismissed] = useState(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'))
    } catch {
      return new Set()
    }
  })

  const list = sources || []
  const health = healthPayload?.sources || []
  const steps = []

  if (list.length === 0) {
    steps.push({
      id: 'connect-source',
      label: 'Connect a data source',
      detail: 'Nothing is configured yet; every number on this platform starts at a feed.',
      action: () => navigate('datasources')
    })
  } else if (!list.some((source) => source.last_successful_fetch)) {
    steps.push({
      id: 'first-collection',
      label: 'Run your first collection',
      detail: 'Sources are configured but nothing has been fetched, so the gates have nothing to certify.',
      action: () => navigate('datasources')
    })
  }

  if (list.length > 0 && !health.some((row) => row.scheduled)) {
    steps.push({
      id: 'schedule',
      label: 'Put a feed on a schedule',
      detail: 'Every source is manual-only right now; a cadence is what turns a fetch into monitoring.',
      action: () => navigate('datasources')
    })
  }

  if (networkPayload?.status !== 'available') {
    steps.push({
      id: 'exposures',
      label: 'Upload or estimate interbank exposures',
      detail: 'The risk map has no exposure matrix yet; declared marginals are enough to estimate one, labelled as an estimate.',
      action: () => navigate('globe')
    })
  }

  const visible = steps.filter((step) => !dismissed.has(step.id))
  if (visible.length === 0) return null

  const dismiss = (id) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(id)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(next)))
      return next
    })
  }

  return (
    <Card accent="pine" className="bg-bne-pine-50/60 border-bne-pine-100">
      <div className="px-5 py-4">
        <p className="bne-micro mb-2 text-bne-pine">Getting the platform talking</p>
        <ul className="space-y-2">
          {visible.map((step) => (
            <li key={step.id} className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-bne-ink">{step.label}</p>
                <p className="text-xs text-bne-muted">{step.detail}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button variant="outline" size="sm" onClick={step.action}>
                  Open
                </Button>
                <button
                  type="button"
                  onClick={() => dismiss(step.id)}
                  className="text-xs text-bne-faint hover:text-bne-ink underline underline-offset-2"
                >
                  dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}
