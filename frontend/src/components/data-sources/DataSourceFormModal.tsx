import { useEffect, useMemo, useState, type FormEvent } from 'react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import type {
  DataSource,
  DataSourceFormPayload,
  PluginConfigField,
  PluginOption
} from '../../types/api'

const SECRET_MASK = '********'

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return '{\n  \n}'
  }
}

function fieldDefault(field: PluginConfigField): unknown {
  if (field.default !== undefined) return field.default
  if (field.type === 'boolean') return false
  if (field.type === 'multi-select' || field.type === 'array') return []
  return ''
}

function initialConfigValues(
  schema: Record<string, PluginConfigField> | null | undefined,
  config: Record<string, unknown>
): Record<string, unknown> {
  return Object.entries(schema || {}).reduce<Record<string, unknown>>((values, [key, field]) => {
    const saved = config[key]
    if (field.secret) {
      values[key] = ''
    } else if (saved !== undefined && saved !== null) {
      values[key] = field.type === 'dict' || field.type === 'object' ? formatJson(saved) : saved
    } else {
      values[key] = fieldDefault(field)
    }
    return values
  }, {})
}

function optionEntries(field: PluginConfigField): Array<{ value: string; label: string }> {
  return (field.options || []).map((option) =>
    typeof option === 'string' ? { value: option, label: option } : option
  )
}

export interface DataSourceFormModalProps {
  isOpen: boolean
  mode?: 'create' | 'edit'
  initialSource?: DataSource | null
  pluginOptions?: PluginOption[] | null
  onClose?: () => void
  onSubmit?: (payload: DataSourceFormPayload) => Promise<void> | void
}

export default function DataSourceFormModal({
  isOpen,
  mode = 'create',
  initialSource,
  pluginOptions,
  onClose,
  onSubmit
}: DataSourceFormModalProps) {
  const [name, setName] = useState('')
  const [pluginType, setPluginType] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [registrationUrl, setRegistrationUrl] = useState('')
  const [registrationRequired, setRegistrationRequired] = useState(false)
  const [freeTierLimits, setFreeTierLimits] = useState('')
  const [coverageDescription, setCoverageDescription] = useState('')
  const [configText, setConfigText] = useState('')
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const pluginValues = useMemo(() => pluginOptions || [], [pluginOptions])
  const selectedPlugin = useMemo(
    () => pluginValues.find((plugin) => plugin.value === pluginType) || null,
    [pluginValues, pluginType]
  )
  const configSchema = selectedPlugin?.config_schema || {}
  const configFields = Object.entries(configSchema)

  useEffect(() => {
    if (!isOpen) return

    const source = initialSource || ({} as Partial<DataSource>)
    const nextPluginType = source.plugin_type || pluginValues[0]?.value || ''
    const nextConfig = source.config || {}
    const nextPlugin = pluginValues.find((plugin) => plugin.value === nextPluginType)

    setName(source.name || '')
    setPluginType(nextPluginType)
    setDescription(source.description || '')
    setEnabled(source.enabled !== undefined && source.enabled !== null ? source.enabled : true)
    setRegistrationUrl(source.registration_url || '')
    setRegistrationRequired(source.registration_required || false)
    setFreeTierLimits(source.free_tier_limits || '')
    setCoverageDescription(source.coverage_description || '')
    setConfigText(formatJson(nextConfig))
    setConfigValues(initialConfigValues(nextPlugin?.config_schema, nextConfig))
    setError(null)
    setIsSubmitting(false)
  }, [isOpen, initialSource, pluginValues])

  const handlePluginChange = (nextPluginType: string) => {
    setPluginType(nextPluginType)
    const nextPlugin = pluginValues.find((plugin) => plugin.value === nextPluginType)
    setConfigValues(initialConfigValues(nextPlugin?.config_schema, {}))
    setConfigText('{}')
    setError(null)
  }

  const setConfigValue = (key: string, value: unknown) => {
    setConfigValues((previous) => ({ ...previous, [key]: value }))
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (!name.trim()) {
      setError('Name is required.')
      return
    }

    if (!pluginType) {
      setError('Select a plugin type.')
      return
    }

    let parsedConfig: Record<string, unknown> = {}
    if (configText.trim()) {
      try {
        const parsed = JSON.parse(configText) as unknown
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          setError('Configuration (JSON) must contain an object.')
          return
        }
        parsedConfig = parsed as Record<string, unknown>
      } catch {
        setError('Configuration (JSON) must be valid JSON.')
        return
      }
    }

    for (const [key, field] of configFields) {
      if (field.type === 'info') continue
      const rawValue = configValues[key]
      const hasAdvancedValue = Object.prototype.hasOwnProperty.call(parsedConfig, key)
      const isBlank = rawValue === '' || rawValue === undefined || rawValue === null
      const isEmptyList = Array.isArray(rawValue) && rawValue.length === 0
      const requiredValueMissing =
        Boolean(field.required) &&
        isBlank &&
        !hasAdvancedValue &&
        !(field.secret && initialSource?.config?.[key] === SECRET_MASK)

      if (requiredValueMissing) {
        setError(`${field.label || key} is required.`)
        return
      }

      if (field.secret && isBlank) continue
      if (!field.required && isBlank && !hasAdvancedValue) continue
      if (!field.required && isEmptyList && !hasAdvancedValue) continue

      let value = rawValue
      if (field.type === 'dict' || field.type === 'object' || field.type === 'array') {
        if (typeof rawValue === 'string') {
          try {
            value = JSON.parse(rawValue)
          } catch {
            setError(`${field.label || key} must contain valid JSON.`)
            return
          }
        }
      }
      if (field.type === 'number' || field.type === 'integer') {
        value = rawValue === '' ? '' : Number(rawValue)
      }
      parsedConfig[key] = value
    }

    const payload: DataSourceFormPayload = {
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
      setError(
        submitError instanceof Error ? submitError.message : 'Failed to save data source. Please try again.'
      )
      setIsSubmitting(false)
    }
  }

  const renderConfigField = (key: string, field: PluginConfigField) => {
    const type = field.type || 'string'
    const label = field.label || key
    const value = configValues[key]
    const className =
      'rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine'
    const options = optionEntries(field)

    if (type === 'info') {
      return (
        <div key={key} className="rounded-lg bg-bne-paper/60 px-3 py-2 text-xs text-bne-muted">
          <span className="font-medium text-bne-ink">{label}: </span>
          {field.help || field.description}
        </div>
      )
    }

    let control: JSX.Element
    if (type === 'boolean') {
      control = (
        <label className="flex items-center gap-2 text-sm text-bne-muted">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => setConfigValue(key, event.target.checked)}
            className="h-4 w-4 rounded border-bne-line text-bne-pine focus:ring-bne-pine"
          />
          {label}
        </label>
      )
    } else if (type === 'multi-select') {
      const selected = Array.isArray(value) ? value.map(String) : []
      control = (
        <select
          multiple
          aria-label={label}
          value={selected}
          onChange={(event) =>
            setConfigValue(
              key,
              Array.from(event.target.selectedOptions).map((option) => option.value)
            )
          }
          className={`${className} min-h-24`}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )
    } else if ((type === 'select' || type === 'choice' || type === 'enum') && options.length > 0) {
      control = (
        <select
          aria-label={label}
          value={String(value ?? '')}
          onChange={(event) => setConfigValue(key, event.target.value)}
          className={className}
        >
          <option value="">Select {label.toLowerCase()}</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )
    } else if (type === 'dict' || type === 'object' || type === 'array') {
      control = (
        <textarea
          aria-label={label}
          rows={4}
          value={typeof value === 'string' ? value : formatJson(value)}
          onChange={(event) => setConfigValue(key, event.target.value)}
          spellCheck={false}
          className={`font-mono ${className}`}
        />
      )
    } else {
      control = (
        <input
          type={field.secret ? 'password' : type === 'number' || type === 'integer' ? 'number' : 'text'}
          aria-label={label}
          value={String(value ?? '')}
          onChange={(event) =>
            setConfigValue(
              key,
              type === 'number' || type === 'integer'
                ? event.target.value === ''
                  ? ''
                  : Number(event.target.value)
                : event.target.value
            )
          }
          placeholder={
            field.secret && initialSource?.config?.[key] === SECRET_MASK
              ? 'Already configured — leave blank to keep it'
              : field.placeholder
          }
          min={field.min}
          max={field.max}
          step={type === 'integer' ? 1 : type === 'number' ? 'any' : undefined}
          autoComplete={field.secret ? 'new-password' : undefined}
          className={className}
        />
      )
    }

    return (
      <label key={key} className="flex flex-col gap-2">
        {type !== 'boolean' && <span className="text-sm font-medium text-bne-muted">{label}</span>}
        {control}
        {(field.help || field.description) && (
          <span className="text-xs text-bne-muted">{field.help || field.description}</span>
        )}
      </label>
    )
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
            <span className="text-sm font-medium text-bne-muted">Name</span>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-muted">Plugin Type</span>
            <select
              aria-label="Plugin Type"
              value={pluginType}
              onChange={(event) => handlePluginChange(event.target.value)}
              className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
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

        {selectedPlugin?.description && (
          <div className="rounded-lg border border-bne-pine/20 bg-bne-pine/5 px-4 py-3 text-sm text-bne-muted">
            <p>{selectedPlugin.description}</p>
            {selectedPlugin.registration_url && (
              <a
                href={selectedPlugin.registration_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-bne-pine underline"
              >
                Provider registration / documentation
              </a>
            )}
          </div>
        )}

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-muted">Description</span>
          <textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
          />
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex items-center gap-2 text-sm text-bne-muted">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="h-4 w-4 rounded border-bne-line text-bne-pine focus:ring-bne-pine"
            />
            Enabled
          </label>

          <label className="flex items-center gap-2 text-sm text-bne-muted">
            <input
              type="checkbox"
              checked={registrationRequired}
              onChange={(event) => setRegistrationRequired(event.target.checked)}
              className="h-4 w-4 rounded border-bne-line text-bne-pine focus:ring-bne-pine"
            />
            Registration required
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-muted">Registration URL</span>
            <input
              type="url"
              value={registrationUrl}
              onChange={(event) => setRegistrationUrl(event.target.value)}
              placeholder="https://"
              className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium text-bne-muted">Free Tier Limits</span>
            <input
              type="text"
              value={freeTierLimits}
              onChange={(event) => setFreeTierLimits(event.target.value)}
              className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
            />
          </label>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-muted">Coverage Description</span>
          <textarea
            rows={2}
            value={coverageDescription}
            onChange={(event) => setCoverageDescription(event.target.value)}
            className="rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
          />
        </label>

        {configFields.length > 0 && (
          <div className="space-y-4 rounded-xl border border-bne-line bg-bne-paper/30 p-4">
            <div>
              <h3 className="text-sm font-semibold text-bne-ink">Provider settings</h3>
              <p className="mt-1 text-xs text-bne-muted">
                These fields come from the selected plugin. Secret values are never displayed after saving.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {configFields.map(([key, field]) => renderConfigField(key, field))}
            </div>
          </div>
        )}

        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium text-bne-muted">Configuration (JSON)</span>
          <span className="text-xs text-bne-muted">
            Advanced settings are preserved here. For API keys, use the provider fields above.
          </span>
          <textarea
            rows={8}
            value={configText}
            onChange={(event) => setConfigText(event.target.value)}
            spellCheck={false}
            className="font-mono rounded-lg border border-bne-line px-3 py-2 text-sm text-bne-ink focus:border-bne-pine focus:outline-none focus:ring-2 focus:ring-bne-pine"
          />
        </label>

        {error && (
          <div className="rounded-lg border border-bne-clay/30 bg-bne-clay/10 px-4 py-3 text-sm text-bne-clay">
            {error}
          </div>
        )}
      </form>
    </Modal>
  )
}
