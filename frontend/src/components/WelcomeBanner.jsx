import { useState } from 'react'
import Card from './ui/Card'
import Button from './ui/Button'
import { BeaconMark } from './Brand'
import { useOnboarding } from '../hooks/useOnboarding'

export default function WelcomeBanner() {
  const { hasCompletedOnboarding, startOnboarding } = useOnboarding()
  const [isDismissed, setIsDismissed] = useState(false)

  // Don't show if onboarding completed or banner dismissed
  if (hasCompletedOnboarding || isDismissed) {
    return null
  }

  return (
    <Card accent="pine" className="bg-bne-pine-50/70 border-bne-pine-100">
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-11 h-11 bg-bne-card border border-bne-pine-100 rounded-md flex items-center justify-center">
          <BeaconMark className="w-7 h-7" />
        </div>

        <div className="flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="bne-micro mb-1 text-bne-pine">Orientation</p>
              <h3 className="font-display text-lg font-semibold text-bne-ink mb-1">
                Welcome to BEACON
              </h3>
              <p className="text-[13.5px] leading-relaxed text-bne-muted mb-4 max-w-2xl">
                Take the guided tour to see how systemic liquidity risk is monitored
                across banking networks — from the data-quality gate to the risk map
                and model performance.
              </p>
            </div>
            <button
              onClick={() => setIsDismissed(true)}
              className="text-bne-faint hover:text-bne-ink transition-colors p-1 rounded"
              aria-label="Dismiss welcome banner"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex items-center gap-3">
            <Button variant="primary" size="sm" onClick={startOnboarding}>
              <svg className="w-4 h-4 mr-1.5 inline-block -mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Start Tour
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setIsDismissed(true)}>
              Maybe Later
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
