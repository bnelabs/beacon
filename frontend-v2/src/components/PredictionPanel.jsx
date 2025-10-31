import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  fetchModelDetail,
  createJob,
  fetchJob,
  fetchPredictionReport,
} from '../api/dataExplorer.js'
import { useUIStore } from '../state/uiStore.js'

function PredictionNodes({ report }) {
  if (!report || report.nodes.length === 0) {
    return (
      <p className="text-xs text-bne-steel/70">No prediction nodes available.</p>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 text-xs text-bne-steel/80">
      {report.nodes.map((node) => (
        <div key={node.source} className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-bne-ink">{node.source}</span>
            <span>{(node.risk * 100).toFixed(1)}%</span>
          </div>
          {node.confidence_lower !== null && node.confidence_upper !== null ? (
            <p className="mt-1 text-[11px] text-bne-steel/60">
              Confidence [{(node.confidence_lower * 100).toFixed(1)}%, {(node.confidence_upper * 100).toFixed(1)}%]
            </p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function FeatureImportances({ report }) {
  const entries = Object.entries(report?.feature_importances ?? {}).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return null
  return (
    <div className="rounded-3xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
      <p className="text-sm font-semibold text-bne-ink">Top Drivers</p>
      <ul className="mt-2 space-y-1">
        {entries.slice(0, 5).map(([feature, importance]) => (
          <li key={feature} className="flex items-center justify-between">
            <span>{feature}</span>
            <span>{importance.toFixed(3)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function PredictionPanel({ modelId }) {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const dataJobId = useUIStore((state) => state.dataJobId)
  const predictionJobId = useUIStore((state) => state.predictionJobId)
  const setPredictionJobId = useUIStore((state) => state.setPredictionJobId)
  const confirmedRegions = useUIStore((state) => state.confirmedRegions)
  const confirmedCountries = useUIStore((state) => state.confirmedCountries)
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const selectedCountries = useUIStore((state) => state.selectedCountries)

  const detailQuery = useQuery({
    queryKey: ['model-detail', modelId],
    queryFn: () => fetchModelDetail(modelId),
    enabled: Boolean(modelId),
  })

  const [formValues, setFormValues] = useState({
    horizon_days: 7,
    volatility: 0.18,
    funding_spread_bps: 50,
  })

  const predictionMutation = useMutation({
    mutationFn: (payload) => createJob(payload),
    onSuccess: (data) => setPredictionJobId(data.id),
  })

  const jobQuery = useQuery({
    queryKey: ['job-status', predictionJobId],
    queryFn: () => fetchJob(predictionJobId),
    enabled: Boolean(predictionJobId),
    refetchInterval: (data) => {
      if (!data) return false
      const status = data.status
      return status && !['completed', 'failed'].includes(status) ? 4000 : false
    },
  })

  const reportQuery = useQuery({
    queryKey: ['prediction-report', predictionJobId],
    queryFn: () => fetchPredictionReport(predictionJobId),
    enabled: Boolean(predictionJobId) && jobQuery.data?.status === 'completed',
    staleTime: 0,
  })

  const jobData = jobQuery.data
  const status = jobData?.status
  const progress = jobData?.progress ?? 0
  const currentStep = jobData?.current_step
  const error = jobData?.error_message || jobData?.user_friendly_error
  const completed = status === 'completed'

  const modelDetail = detailQuery.data

  const handleChange = (key, value) => {
    setFormValues((prev) => ({ ...prev, [key]: value }))
  }

  const scopeRegions = confirmedRegions.length > 0 ? confirmedRegions : selectedRegions
  const scopeCountries = confirmedCountries.length > 0 ? confirmedCountries : selectedCountries

  const handleStart = () => {
    if (!modelId) return
    const payload = {
      job_type: 'prediction',
      parameters: {
        trained_model_job: modelId,
        forecast_horizon: formValues.horizon_days,
        config: {
          volatility: formValues.volatility,
          funding_spread_bps: formValues.funding_spread_bps,
          data_job_id: dataJobId,
        },
        regions: scopeRegions,
        countries: scopeCountries,
      },
    }
    predictionMutation.mutate(payload)
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-bne-azure">Prediction</p>
          <h2 className="mt-2 text-xl font-semibold text-bne-ink">What-if analysis</h2>
        </div>
        <button
          type="button"
          onClick={() => setPanelStage('model-library')}
          className="rounded-full border border-bne-silver/60 px-4 py-1.5 text-xs font-medium text-bne-steel transition hover:border-bne-azure/60 hover:text-bne-azure"
        >
          Back to models
        </button>
      </div>

      {modelDetail ? (
        <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
          <p className="text-sm font-semibold text-bne-ink">Model: {modelDetail.result?.model_type ?? 'N/A'}</p>
          <p className="mt-1">Best epoch: {modelDetail.result?.best_epoch ?? 'n/a'}</p>
        </div>
      ) : null}

      <div className="rounded-2xl border border-bne-silver/60 bg-white/70 p-4 text-xs text-bne-steel/80">
        <p className="text-sm font-semibold text-bne-ink">Operational Scope</p>
        <p className="mt-2">
          Regions: {scopeRegions.length > 0 ? scopeRegions.join(', ') : 'All tracked regions'}
        </p>
        {scopeCountries.length > 0 ? (
          <p>
            Country focus: {scopeCountries.join(', ')}
          </p>
        ) : (
          <p>Country focus: All countries within selected regions</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm text-bne-steel/80">
        <label className="flex flex-col gap-1">
          <span>Horizon (days)</span>
          <input
            type="number"
            min="1"
            max="30"
            value={formValues.horizon_days}
            onChange={(event) => handleChange('horizon_days', Number(event.target.value))}
            className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Volatility shock</span>
          <input
            type="number"
            step="0.01"
            value={formValues.volatility}
            onChange={(event) => handleChange('volatility', Number(event.target.value))}
            className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-azure/40"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Funding spread (bps)</span>
          <input
            type="number"
            value={formValues.funding_spread_bps}
            onChange={(event) => handleChange('funding_spread_bps', Number(event.target.value))}
            className="rounded-xl border border-bne-silver/60 bg-white/80 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-bne-emerald/40"
          />
        </label>
      </div>

      {predictionJobId === null ? (
        <button
          type="button"
          onClick={handleStart}
          disabled={predictionMutation.isLoading}
          className="w-full rounded-full bg-bne-azure px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-azure/90 disabled:cursor-not-allowed disabled:bg-bne-silver/60"
        >
          {predictionMutation.isLoading ? 'Submitting…' : 'Run Prediction'}
        </button>
      ) : (
        <div className="rounded-3xl bg-white/70 p-5 shadow-bne-panel">
          <div className="flex items-center justify-between text-sm font-medium text-bne-ink">
            <span>Status: {status}</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="mt-3 h-2 rounded-full bg-bne-ice">
            <div className="h-full rounded-full bg-bne-azure transition-all" style={{ width: `${Math.min(100, Math.round(progress))}%` }} />
          </div>
          {currentStep ? <p className="mt-2 text-xs text-bne-steel/70">{currentStep}</p> : null}
          {error ? <p className="mt-3 text-xs text-red-600">{error}</p> : null}
        </div>
      )}

      {completed ? (
        <motion.div layout className="space-y-4">
          <div className="rounded-3xl border border-bne-silver/60 bg-white/80 p-5 shadow-sm text-xs text-bne-steel/80">
            <p className="text-sm font-semibold text-bne-ink">Prediction Summary</p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              {Object.entries(reportQuery.data?.summary_metrics ?? {}).map(([key, value]) => (
                <p key={key} className="capitalize">
                  {key.replace('_', ' ')}: {typeof value === 'number' ? value.toFixed(4) : value}
                </p>
              ))}
            </div>
          </div>

          <PredictionNodes report={reportQuery.data} />
          <FeatureImportances report={reportQuery.data} />
        </motion.div>
      ) : null}
    </div>
  )
}
