import { useEffect, useState } from 'react'
import { driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useRouter } from '../store/useRouter'

const ONBOARDING_STORAGE_KEY = 'beacon-onboarding-completed'

export function useOnboarding() {
  const [hasCompletedOnboarding, setHasCompletedOnboarding] = useState(
    () => localStorage.getItem(ONBOARDING_STORAGE_KEY) === 'true'
  )
  const { navigate } = useRouter()

  const startOnboarding = () => {
    const driverObj = driver({
      showProgress: true,
      showButtons: ['next', 'previous', 'close'],
      progressText: '{{current}} of {{total}}',
      nextBtnText: 'Next →',
      prevBtnText: '← Previous',
      doneBtnText: 'Get Started!',
      popoverClass: 'beacon-onboarding-popover',

      steps: [
        {
          element: 'body',
          popover: {
            title: 'Welcome to BEACON 👋',
            description: `
              <div class="space-y-3">
                <p><strong>Banking Early Alert Comprehensive Observation Network</strong></p>
                <p>BEACON uses advanced machine learning to monitor systemic liquidity risk across global banking networks.</p>
                <p>Let's take a quick tour to get you started!</p>
              </div>
            `,
            side: 'center',
            align: 'center'
          }
        },
        {
          element: '[data-tour="globe-nav"]',
          popover: {
            title: '🌍 Globe View',
            description: `
              <div class="space-y-2">
                <p>Visualize banking regions and data sources on an interactive 3D globe.</p>
                <p><strong>Features:</strong></p>
                <ul class="list-disc pl-5 space-y-1">
                  <li>Click regions to view banking data</li>
                  <li>Toggle network visualization to see interbank connections</li>
                  <li>Color-coded risk levels (green → red)</li>
                </ul>
              </div>
            `,
            side: 'right',
            align: 'start',
            onNextClick: () => {
              navigate('globe')
              driverObj.moveNext()
            }
          }
        },
        {
          element: '[data-tour="models-nav"]',
          popover: {
            title: '🧠 Models',
            description: `
              <div class="space-y-2">
                <p>Configure and manage your machine learning models.</p>
                <p><strong>Available Models:</strong></p>
                <ul class="list-disc pl-5 space-y-1">
                  <li><strong>HGT</strong> - Heterogeneous Graph Transformer</li>
                  <li><strong>Temporal GNN</strong> - Time-series graph analysis</li>
                  <li><strong>Multi-scale</strong> - Multi-resolution networks</li>
                </ul>
                <p class="text-sm text-gray-600">Models are EU AI Act compliant with SHAP explainability.</p>
              </div>
            `,
            side: 'right',
            align: 'start',
            onNextClick: () => {
              navigate('models')
              driverObj.moveNext()
            }
          }
        },
        {
          element: '[data-tour="jobs-nav"]',
          popover: {
            title: '⏱️ Jobs',
            description: `
              <div class="space-y-2">
                <p>Create and monitor model training, predictions, and backtests.</p>
                <p><strong>Job Types:</strong></p>
                <ul class="list-disc pl-5 space-y-1">
                  <li><strong>Training</strong> - Train models on historical data</li>
                  <li><strong>Prediction</strong> - Generate risk forecasts</li>
                  <li><strong>Backtest</strong> - Validate model performance</li>
                </ul>
                <p class="mt-2">Monitor progress in real-time with live status updates.</p>
              </div>
            `,
            side: 'right',
            align: 'start',
            onNextClick: () => {
              navigate('jobs')
              driverObj.moveNext()
            }
          }
        },
        {
          element: '[data-tour="results-nav"]',
          popover: {
            title: '📈 Results',
            description: `
              <div class="space-y-2">
                <p>Analyze predictions, risk scores, and model performance.</p>
                <p><strong>Insights:</strong></p>
                <ul class="list-disc pl-5 space-y-1">
                  <li>Risk predictions with confidence intervals</li>
                  <li>Time-series forecasts and trends</li>
                  <li>SHAP values for model explainability</li>
                  <li>Interactive charts and visualizations</li>
                </ul>
              </div>
            `,
            side: 'right',
            align: 'start'
          }
        },
        {
          element: '[data-tour="search-button"]',
          popover: {
            title: '🔍 Pro Tip: Global Search',
            description: `
              <div class="space-y-2">
                <p>Press <kbd class="px-2 py-1 bg-gray-100 rounded border text-sm font-mono">⌘K</kbd> (or <kbd class="px-2 py-1 bg-gray-100 rounded border text-sm font-mono">Ctrl+K</kbd>) to quickly search across:</p>
                <ul class="list-disc pl-5 space-y-1">
                  <li>All pages and navigation</li>
                  <li>Jobs and their statuses</li>
                  <li>Models and configurations</li>
                  <li>Country profiles</li>
                  <li>Data catalogue items</li>
                </ul>
                <p class="mt-2 text-sm text-gray-600">Use arrow keys to navigate results, Enter to select.</p>
              </div>
            `,
            side: 'bottom',
            align: 'end'
          }
        },
        {
          element: 'body',
          popover: {
            title: 'You\'re All Set! 🎉',
            description: `
              <div class="space-y-3">
                <p>You now know the basics of BEACON. Here's what to do next:</p>
                <ol class="list-decimal pl-5 space-y-2">
                  <li><strong>Configure Data Sources</strong> - Connect FDIC, ECB, or FMP data</li>
                  <li><strong>Create Your First Job</strong> - Train a model or run predictions</li>
                  <li><strong>Explore Country Profiles</strong> - Pre-evaluate economic metrics</li>
                  <li><strong>Check Help Center</strong> - For detailed documentation</li>
                </ol>
                <p class="mt-3 text-sm text-gray-600">You can restart this tour anytime from Settings → Onboarding.</p>
              </div>
            `,
            side: 'center',
            align: 'center'
          }
        }
      ],

      onDestroyed: () => {
        // Mark onboarding as completed
        localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true')
        setHasCompletedOnboarding(true)
        navigate('dashboard')
      }
    })

    driverObj.drive()
  }

  const resetOnboarding = () => {
    localStorage.removeItem(ONBOARDING_STORAGE_KEY)
    setHasCompletedOnboarding(false)
  }

  return {
    hasCompletedOnboarding,
    startOnboarding,
    resetOnboarding
  }
}
