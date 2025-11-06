import { useState } from 'react'
import Card from './ui/Card'
import Button from './ui/Button'
import { useOnboarding } from '../hooks/useOnboarding'

export default function WelcomeBanner() {
  const { hasCompletedOnboarding, startOnboarding } = useOnboarding()
  const [isDismissed, setIsDismissed] = useState(false)

  // Don't show if onboarding completed or banner dismissed
  if (hasCompletedOnboarding || isDismissed) {
    return null
  }

  return (
    <Card className="bg-gradient-to-r from-bne-azure/10 via-bne-indigo/10 to-bne-violet/10 border-bne-azure/30">
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-12 h-12 bg-gradient-to-br from-bne-azure to-bne-indigo rounded-xl flex items-center justify-center">
          <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>

        <div className="flex-1">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-lg font-semibold text-bne-ink mb-1">
                Welcome to BEACON! 👋
              </h3>
              <p className="text-sm text-bne-steel mb-4">
                Get started with a quick guided tour to learn about key features and how to monitor systemic liquidity risk across banking networks.
              </p>
            </div>
            <button
              onClick={() => setIsDismissed(true)}
              className="text-bne-steel hover:text-bne-ink transition-colors p-1"
              aria-label="Dismiss welcome banner"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              size="sm"
              onClick={startOnboarding}
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Start Tour
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsDismissed(true)}
            >
              Maybe Later
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
