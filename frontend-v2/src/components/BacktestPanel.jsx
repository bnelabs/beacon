import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchModelDetail,
  createJob,
  fetchJob,
  fetchBacktestReport,
} from '../api/dataExplorer.js'
import { useUIStore } from '../state/uiStore.js'

export function BacktestPanel({ modelId }) {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const backtestJobId = useUIStore((state) => state.backtestJobId)
  const setBacktestJobId = useUIStore((state) => state.setBacktestJobId)
  const confirmedRegions = useUIStore((state) => state.confirmedRegions)
  const confirmedCountries = useUIStore((state) => state.confirmedCountries)
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const selectedCountries = useUIStore((state) => state.selectedCountries)

  const detailQuery = useQuery({
    queryKey: ['model-detail', modelId],
    queryFn: () => fetchModelDetail(modelId),
    enabled: Boolean(modelId),
  })

  const [dateRange, setDateRange] = useState({ start: '', end: '' })

  const scopeRegions = confirmedRegions.length > 0 ? confirmedRegions : selectedRegions
  const scopeCountries = confirmedCountries.length > 0 ? confirmedCountries : selectedCountries

  const backtestMutation = useMutation({
    mutationFn: (payload) => createJob(payload),
    onSuccess: (data) => setBacktestJobId(data.id),
  })

  const jobQuery = useQuery({
    queryKey: ['job-status', backtestJobId],
    queryFn: () => fetchJob(backtestJobId),
    enabled: Boolean(backtestJobId),
    refetchInterval: (data) => {
      if (!data) return false
      const status = data.status
      return status && !['completed', 'failed'].includes(status) ? 4000 : false
    },
  })

  const reportQuery = useQuery({
    queryKey: ['backtest-report', backtestJobId],
    queryFn: () => fetchBacktestReport(backtestJobId),
    enabled: Boolean(backtestJobId) && jobQuery.data?.status === 'completed',
    staleTime: 0,
  })

  const jobData = jobQuery.data
  const status = jobData?.status
  const progress = jobData?.progress ?? 0
  const currentStep = jobData?.current_step
  const error = jobData?.error_message || jobData?.user_friendly_error
  const completed = status === 'completed'

  const handleStart = () => {
    const parameters = { trained_model_job: modelId }
    if (dateRange.start) parameters.start_date = dateRange.start
    if (dateRange.end) parameters.end_date = dateRange.end

    parameters.regions = scopeRegions
    parameters.countries = scopeCountries

    const payload = {
      job_type: 'backtest',
      parameters,
    }
    backtestMutation.mutate(payload)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-bne-azure">Backtest</p>
          <h2 className="mt-2 text-xl font-semibold text-bne-ink">Historical validation</h2>
        </div>
        <button
          type="button"
          onClick={() => setPanelStage('model-library')}
          className="rounded-full border border-bne-silver/60 px-4 py-1.5 text-xs font-medium text-bne-steel transition hover:border-bne-emerald/60 hover:text-bne-emerald"
        >
          Back to models
        </button>
      </div>

      {detailQuery.data ? (
        <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
          <p className="text-sm font-semibold text-bne-ink">Model: {detailQuery.data.result?.model_type ?? 'N/A'}</p>
          <p className="mt-1">Training completed: {detailQuery.data.completed_at ?? 'n/a'}</p>
        </div>
      ) : null}

      <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
        <p className="text-sm font-semibold text-bne-ink">Operational Scope</p>
        <p className="mt-2">
          Regions: {scopeRegions.length > 0 ? scopeRegions.join(', ') : 'All'}
        </p>
        {scopeCountries.length > 0 ? (
          <p>Country focus: {scopeCountries.join(', ')}</p>
        ) : (
          <p>Country focus: All countries within region selection</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm text-bne-steel/80">
        <label className="flex flex-col gap-1">
          <span>Start Date</span>
          <input
            type="date"
            value={dateRange.start}
            onChange={(event) => setDateRange((prev) => ({ ...prev, start: event.target.value }))}
            className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>End Date</span>
          <input
            type="date"
            value={dateRange.end}
            onChange={(event) => setDateRange((prev) => ({ ...prev, end: event.target.value }))}
            className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
          />
        </label>
      </div>

      {backtestJobId === null ? (
        <button
          type="button"
          onClick={handleStart}
          disabled={backtestMutation.isLoading}
          className="w-full rounded-full bg-bne-emerald px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-emerald/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
        >
          {backtestMutation.isLoading ? 'Submitting…' : 'Run Backtest'}
        </button>
      ) : (
        <div className="rounded-3xl bg-white/70 p-5 shadow-bne-panel">
          <div className="flex items-center justify-between text-sm font-medium text-bne-ink">
            <span>Status: {status}</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-bne-ice">
            <div className="h-full rounded-full bg-bne-emerald transition-all" style={{ width: `${Math.min(100, Math.round(progress))}%` }} />
          </div>
          {currentStep ? <p className="mt-2 text-xs text-bne-steel/70">{currentStep}</p> : null}
          {error ? <p className="mt-3 text-xs text-red-600">{error}</p> : null}
        </div>
      )}

      {completed ? (
        <div className="rounded-3xl border border-bne-silver/60 bg-white/80 p-5 shadow-sm text-xs text-bne-steel/80">
          <p className="text-sm font-semibold text-bne-ink">Backtest Metrics</p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            {Object.entries(reportQuery.data?.metrics ?? {}).map(([key, value]) => (
              <p key={key} className="capitalize">
                {key.replace('_', ' ')}: {typeof value === 'number' ? value.toFixed(4) : value}
              </p>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-bne-steel/60">
            Train samples: {reportQuery.data?.metadata?.train_samples ?? 'n/a'} | Test samples: {reportQuery.data?.metadata?.test_samples ?? 'n/a'}
          </p>
        </div>
      ) : null}
    </div>
  )
}
