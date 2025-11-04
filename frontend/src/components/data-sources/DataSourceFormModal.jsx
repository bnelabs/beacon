import { useEffect, useMemo, useState } from 'react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'

function formatJson(value) {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch (error) {
    return '{\n  \n}'
  }
}

export default function DataSourceFormModal({
  isOpen,
  mode = 'create',
  initialSource,
  pluginOptions,
  onClose,
  onSubmit
}) {
  const [name, setName] = useState('')
  const [pluginType, setPluginType] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [registrationUrl, setRegistrationUrl] = useState('')
  const [registrationRequired, setRegistrationRequired] = useState(false)
  const [freeTierLimits, setFreeTierLimits] = useState('')
  const [coverageDescription, setCoverageDescription] = useState('')
  const [configText, setConfigText] = useState('')
  const [error, setError] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const pluginValues = useMemo(() => pluginOptions || [], [pluginOptions])

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const source = initialSource || {}
    setName(source.name || '')
    setPluginType(source.plugin_type || pluginValues[0]?.value || '')
    setDescription(source.description || '')
    setEnabled(source.enabled !== undefined ? source.enabled : true)
    setRegistrationUrl(source.registration_url || '')
    setRegistrationRequired(source.registration_required || false)
    setFreeTierLimits(source.free_tier_limits || '')
    setCoverageDescription(source.coverage_description || '')
    setConfigText(formatJson(source.config || {}))
    setError(null)
    setIsSubmitting(false)
  }, [isOpen, initialSource, pluginValues])

  const handleSubmit = async (event) => {
    event.preventDefault()

    if (!name.trim()) {
      setError('Name is required.')
      return
    }

    if (!pluginType) {
      setError('Select a plugin type.')
      return
    }

    let parsedConfig = {}
    if (configText.trim()) {
      try {
        parsedConfig = JSON.parse(configText)
      } catch (parseError) {
        setError('Config must be valid JSON.')
        return
      }
    }

    const payload = {
      name: name.trim(),
      plugin_type: pluginType,
      description: description.trim() || null,
      enabled,
      registration_url: registrationUrl.trim() || null,
      registration_required: registrationRequired,
      free_tier_limits: freeTierLimits.trim() || null,
      coverage_description: coverageDescription.trim() || null,
      config: parsedConfig
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await onSubmit?.(payload)
      setIsSubmitting(false)
      onClose?.()
    } catch (submitError) {
      setError(submitError?.message || 'Failed to save data source. Please try again.')
      setIsSubmitting(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => (isSubmitting ? null : onClose?.())}
      title={mode === 'create' ? 'Add Data Source' : 'Configure Data Source'}
      widthClass="max-w-3xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onClose?.()} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isSubmitting} form="data-source-form">
            {mode === 'create' ? 'Create Source' : 'Save Changes'}
          </Button>
        </>
      }
    >
      <form id="data-source-form" className="space-y-4" onSubmit={handleSubmit}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Name</span>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Plugin Type</span>
            <select
              value={pluginType}
              onChange={(event) => setPluginType(event.target.value)}
              className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
            >
              <option value="" disabled>
                Select plugin
              </option>
              {pluginValues.map((plugin) => (
                <option key={plugin.value} value={plugin.value}>
                  {plugin.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-steel">Description</span>
          <textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
          />
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex items-center gap-2 text-sm text-bne-steel">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="h-4 w-4 rounded border-bne-frost text-bne-azure focus:ring-bne-azure"
            />
            Enabled
          </label>

          <label className="flex items-center gap-2 text-sm text-bne-steel">
            <input
              type="checkbox"
              checked={registrationRequired}
              onChange={(event) => setRegistrationRequired(event.target.checked)}
              className="h-4 w-4 rounded border-bne-frost text-bne-azure focus:ring-bne-azure"
            />
            Registration required
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Registration URL</span>
            <input
              type="url"
              value={registrationUrl}
              onChange={(event) => setRegistrationUrl(event.target.value)}
              placeholder="https://"
              className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-steel">Free Tier Limits</span>
            <input
              type="text"
              value={freeTierLimits}
              onChange={(event) => setFreeTierLimits(event.target.value)}
              className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
            />
          </label>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-steel">Coverage Description</span>
          <textarea
            rows={2}
            value={coverageDescription}
            onChange={(event) => setCoverageDescription(event.target.value)}
            className="rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
          />
        </label>

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-steel">Configuration (JSON)</span>
          <textarea
            rows={8}
            value={configText}
            onChange={(event) => setConfigText(event.target.value)}
            spellCheck={false}
            className="font-mono rounded-lg border border-bne-frost px-3 py-2 text-sm text-bne-ink focus:border-bne-azure focus:outline-none focus:ring-2 focus:ring-bne-azure"
          />
        </label>

        {error && (
          <div className="rounded-lg border border-bne-crimson/30 bg-bne-crimson/10 px-4 py-3 text-sm text-bne-crimson">
            {error}
          </div>
        )}
      </form>
    </Modal>
  )
}
