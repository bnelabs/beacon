import { Component } from 'react'

/**
 * The shell must never white-screen. Before this boundary, one malformed
 * payload on one page unmounted the whole application — a blank paper
 * rectangle with no explanation, no recovery. Now a failing page renders a
 * quiet, honest panel inside the working chrome: what failed, and a way
 * back. Mirrors the backend's fail-closed philosophy at the render layer.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Kept in the console for operators; the panel below stays calm.
    console.error('[beacon] page render failed:', error, info?.componentStack)
  }

  render() {
    if (!this.state.error) {
      return this.props.children
    }

    return (
      <div className="px-7 py-6">
        <div className="rounded-md border border-bne-clay/30 border-l-[3px] border-l-bne-clay bg-bne-clay-50/60 p-6 max-w-2xl">
          <p className="bne-micro mb-1 text-bne-clay-600">This view failed to render</p>
          <h2 className="font-display text-xl font-semibold text-bne-ink mb-2">
            The rest of BEACON is still up
          </h2>
          <p className="text-[13.5px] leading-relaxed text-bne-muted mb-1">
            One view received data it could not draw. Nothing was lost elsewhere in
            the session; navigate to another page to continue.
          </p>
          <p className="font-mono text-xs text-bne-faint break-words">
            {String(this.state.error?.message || this.state.error)}
          </p>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-md bg-bne-pine px-3 py-1.5 text-[13px] font-medium text-bne-chalk hover:bg-bne-pine-600 transition-colors"
            >
              Try this view again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-md border border-bne-line-strong px-3 py-1.5 text-[13px] font-medium text-bne-ink hover:bg-bne-paper-dim transition-colors"
            >
              Reload BEACON
            </button>
          </div>
        </div>
      </div>
    )
  }
}
