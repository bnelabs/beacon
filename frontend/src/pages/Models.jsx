import { useState } from 'react'
import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent, CardFooter } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import LoadingSpinner from '../components/ui/LoadingSpinner'
import ErrorMessage from '../components/ui/ErrorMessage'
import { useModels } from '../hooks/useApi'

function ModelCard({ model }) {
  const statusVariants = {
    ready: 'success',
    training: 'primary',
    failed: 'danger',
    draft: 'default'
  }

  return (
    <Card hover>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>{model.name}</CardTitle>
            <p className="text-sm text-bne-steel mt-1">{model.description}</p>
          </div>
          <Badge variant={statusVariants[model.status] || 'default'}>
            {model.status}
          </Badge>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Architecture</span>
            <span className="font-medium text-bne-ink">{model.architecture || 'LSTM'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Input Features</span>
            <span className="font-medium text-bne-ink">{model.input_features || 12}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Prediction Steps</span>
            <span className="font-medium text-bne-ink">{model.prediction_steps || 4}</span>
          </div>
          {model.accuracy && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-bne-steel">Accuracy</span>
              <span className="font-medium text-bne-emerald">{model.accuracy}%</span>
            </div>
          )}
          <div className="flex items-center justify-between text-sm">
            <span className="text-bne-steel">Last Trained</span>
            <span className="font-medium text-bne-ink">
              {model.last_trained ? new Date(model.last_trained).toLocaleDateString() : 'Never'}
            </span>
          </div>
        </div>
      </CardContent>

      <CardFooter>
        <Button variant="primary" size="sm">
          Train Model
        </Button>
        <Button variant="outline" size="sm">
          View Details
        </Button>
        <Button variant="ghost" size="sm">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
          </svg>
        </Button>
      </CardFooter>
    </Card>
  )
}

function NewModelModal({ isOpen, onClose }) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Create New Model</CardTitle>
            <button
              onClick={onClose}
              className="p-2 hover:bg-bne-frost rounded-lg transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </CardHeader>

        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Model Name
              </label>
              <input
                type="text"
                className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                placeholder="e.g., FDIC Multi-Scale LSTM"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Description
              </label>
              <textarea
                className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                rows={3}
                placeholder="Describe your model..."
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Architecture
                </label>
                <select className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure">
                  <option>LSTM</option>
                  <option>GRU</option>
                  <option>Transformer</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Input Features
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={12}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Sequence Length
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={20}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-bne-ink mb-2">
                  Prediction Steps
                </label>
                <input
                  type="number"
                  className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure"
                  defaultValue={4}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-bne-ink mb-2">
                Data Source
              </label>
              <select className="w-full px-4 py-2 border border-bne-frost rounded-lg focus:outline-none focus:ring-2 focus:ring-bne-azure">
                <option>FDIC</option>
                <option>ECB Banking</option>
                <option>FMP</option>
              </select>
            </div>
          </div>
        </CardContent>

        <CardFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary">
            Create Model
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}

export default function Models() {
  const [showNewModel, setShowNewModel] = useState(false)
  const [filter, setFilter] = useState('all')
  const { data: models, isLoading, error, refetch } = useModels()

  const filteredModels = models?.filter(model => {
    if (filter === 'all') return true
    return model.status === filter
  }) || []

  if (isLoading) {
    return (
      <PageContainer title="Models">
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" message="Loading models..." />
        </div>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer title="Models">
        <ErrorMessage
          title="Failed to load models"
          error={error}
          onRetry={refetch}
        />
      </PageContainer>
    )
  }

  return (
    <>
      <PageContainer
        title="Models"
        actions={
          <Button variant="primary" onClick={() => setShowNewModel(true)}>
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Model
            </span>
          </Button>
        }
      >
        <div className="space-y-6">
          <div className="flex items-center gap-2">
            <Button
              variant={filter === 'all' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('all')}
            >
              All ({models?.length || 0})
            </Button>
            <Button
              variant={filter === 'ready' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('ready')}
            >
              Ready ({models?.filter(m => m.status === 'ready').length || 0})
            </Button>
            <Button
              variant={filter === 'training' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('training')}
            >
              Training ({models?.filter(m => m.status === 'training').length || 0})
            </Button>
            <Button
              variant={filter === 'draft' ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setFilter('draft')}
            >
              Draft ({models?.filter(m => m.status === 'draft').length || 0})
            </Button>
          </div>

          {filteredModels.length === 0 ? (
            <Card className="border-2 border-dashed border-bne-frost bg-bne-ice/50">
              <div className="text-center py-12">
                <svg
                  className="w-16 h-16 mx-auto text-bne-steel/50 mb-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  />
                </svg>
                <h3 className="text-lg font-semibold text-bne-ink mb-2">No models found</h3>
                <p className="text-sm text-bne-steel mb-4">
                  {filter === 'all'
                    ? 'Create your first model to get started'
                    : `No models with status "${filter}"`}
                </p>
                {filter === 'all' && (
                  <Button variant="primary" onClick={() => setShowNewModel(true)}>
                    Create Model
                  </Button>
                )}
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredModels.map((model) => (
                <ModelCard key={model.model_id} model={model} />
              ))}
            </div>
          )}
        </div>
      </PageContainer>

      <NewModelModal isOpen={showNewModel} onClose={() => setShowNewModel(false)} />
    </>
  )
}
