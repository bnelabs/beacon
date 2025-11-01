import { memo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { fetchModels, fetchModelDetail } from '../api/dataExplorer.js'
import { useUIStore } from '../state/uiStore.js'

const ModelCard = memo(function ModelCard({ model, selected, onSelect }) {
  return (
    <motion.button
      type="button"
      layout
      onClick={onSelect}
      className={`w-full rounded-2xl border px-5 py-4 text-left transition ${
        selected
          ? 'border-bne-azure/70 bg-bne-azure/10 shadow-bne-panel'
          : 'border-bne-silver/60 bg-white/70 hover:border-bne-azure/50'
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-bne-ink">{model.name}</p>
          <p className="text-xs uppercase tracking-[0.18em] text-bne-steel/70">{model.model_type}</p>
        </div>
        <div className="text-xs text-bne-steel/70">{model.metrics.mae ? `MAE ${model.metrics.mae.toFixed(4)}` : ''}</div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase text-bne-steel/70">
        {model.tags.map((tag) => (
          <span key={tag} className="rounded-full bg-bne-ice/90 px-2 py-1">
            {tag}
          </span>
        ))}
        {model.predictions_available ? (
          <span className="rounded-full bg-bne-emerald/20 px-2 py-1 text-bne-emerald">Predictions</span>
        ) : null}
      </div>
    </motion.button>
  )
})

export function ModelLibrary() {
  const setPanelStage = useUIStore((state) => state.setPanelStage)
  const selectedModelId = useUIStore((state) => state.selectedModelId)
  const setSelectedModelId = useUIStore((state) => state.setSelectedModelId)

  const modelsQuery = useQuery({
    queryKey: ['models'],
    queryFn: fetchModels,
    staleTime: 60_000,
  })

  const detailQuery = useQuery({
    queryKey: ['model-detail', selectedModelId],
    queryFn: () => fetchModelDetail(selectedModelId),
    enabled: Boolean(selectedModelId),
    staleTime: 30_000,
  })

  const models = modelsQuery.data ?? []
  const detail = detailQuery.data

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-bne-azure">Model Library</p>
          <h2 className="mt-2 text-xl font-semibold text-bne-ink">Select a trained model</h2>
        </div>
        <button
          type="button"
          onClick={() => setPanelStage('training')}
          className="rounded-full border border-bne-silver/60 px-4 py-1.5 text-xs font-medium text-bne-steel transition hover:border-bne-azure/60 hover:text-bne-azure"
        >
          Back to Training
        </button>
      </div>

      {modelsQuery.isLoading ? (
        <div className="flex h-48 items-center justify-center text-sm text-bne-steel/70">Loading models…</div>
      ) : models.length === 0 ? (
        <div className="rounded-3xl border border-bne-silver/60 bg-white/70 p-4 text-sm text-bne-steel/80">
          Train a model to populate the library.
        </div>
      ) : (
        <div className="space-y-3">
          <AnimatePresence initial={false}>
            {models.map((model) => (
              <ModelCard
                key={model.model_id}
                model={model}
                selected={selectedModelId === model.model_id}
                onSelect={() => setSelectedModelId(model.model_id)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      {detail ? (
        <div className="rounded-3xl bg-white/80 p-5 shadow-bne-panel text-xs text-bne-steel/80">
          <p className="text-sm font-semibold text-bne-ink">Model Metrics</p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <p>Best epoch: {detail.result?.best_epoch ?? 'n/a'}</p>
            <p>Final val loss: {detail.result?.final_val_loss?.toFixed(4) ?? 'n/a'}</p>
            <p>Test MAE: {detail.result?.test_mae?.toFixed(4) ?? 'n/a'}</p>
            <p>Test RMSE: {detail.result?.test_rmse?.toFixed(4) ?? 'n/a'}</p>
          </div>
          <button
            type="button"
            onClick={() => setPanelStage('prediction')}
            className="mt-4 w-full rounded-full bg-bne-azure px-5 py-3 text-sm font-semibold text-white transition hover:bg-bne-azure/90"
          >
            Launch Prediction
          </button>
          <button
            type="button"
            onClick={() => setPanelStage('backtest')}
            className="mt-3 w-full rounded-full border border-bne-emerald/50 px-5 py-3 text-sm font-semibold text-bne-emerald transition hover:border-bne-emerald hover:text-bne-ink"
          >
            Run Backtest
          </button>
        </div>
      ) : null}
    </div>
  )
}
