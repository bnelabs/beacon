import { useState } from 'react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { fetchApi } from '../../utils/apiClient'
import type { NetworkEstimateResult } from '../../types/api'

/**
 * The missing half of the network layer: the backend has accepted declared
 * exposure matrices (`POST /network/exposures`) and estimated them from
 * declared marginals (`POST /network/estimate`) since the PIT store landed,
 * but no screen ever offered either, so the risk map's network toggle stayed
 * dead in every deployment. These two modals are that offer.
 *
 * The estimate path carries its caveat with it: the response's `uncertainty`
 * string is rendered verbatim under the result, because an estimated network
 * presented without its prior-status is exactly the kind of quiet invention
 * this platform refuses everywhere else.
 */

interface NetworkIntakeModalProps {
  isOpen: boolean
  onClose?: () => void
  onDone?: (result: unknown) => void
}

export function ExposureUploadModal({ isOpen, onClose, onDone }: NetworkIntakeModalProps) {
  const [institution, setInstitution] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [asOf, setAsOf] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!institution || !file) {
      setError('An attributing institution and a matrix file are both required.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const params = new URLSearchParams({ source_institution: institution })
      if (asOf) params.set('as_of', asOf)
      if (file.name.endsWith('.parquet')) params.set('format', 'parquet')
      else if (file.name.endsWith('.csv')) params.set('format', 'csv')
      const buffer = await file.arrayBuffer()
      const result = await fetchApi(`/v1/network/exposures?${params.toString()}`, {
        method: 'POST',
        body: buffer,
        headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': file.name }
      })
      onDone?.(result)
      onClose?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The upload was refused.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Upload an exposure matrix" widthClass="max-w-xl">
      <div className="space-y-4 px-6 py-5">
        <p className="text-sm text-bne-muted">
          A point-in-time bilateral matrix (CSV or parquet) as published or
          assembled by the attributing institution. Rows are claims of the row
          institution against the column institution; the vintage is stored,
          never inferred.
        </p>
        <label className="block text-sm">
          <span className="text-bne-ink font-medium">Source institution</span>
          <input
            className="mt-1 w-full rounded-lg border border-bne-line px-3 py-2 text-sm focus:border-bne-pine focus:outline-none"
            value={institution}
            onChange={(event) => setInstitution(event.target.value)}
            placeholder="e.g. FDIC call reports, own consolidation"
          />
        </label>
        <label className="block text-sm">
          <span className="text-bne-ink font-medium">Vintage (as_of), optional</span>
          <input
            className="mt-1 w-full rounded-lg border border-bne-line px-3 py-2 text-sm focus:border-bne-pine focus:outline-none"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
            placeholder="ISO date; required to agree with an as_of column"
          />
        </label>
        <label className="block text-sm">
          <span className="text-bne-ink font-medium">Matrix file</span>
          <input
            type="file"
            accept=".csv,.parquet"
            className="mt-1 w-full text-sm text-bne-muted file:mr-3 file:rounded-md file:border file:border-bne-line file:bg-bne-card file:px-3 file:py-1.5 file:text-sm file:text-bne-ink"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        {error && <p className="text-sm text-bne-clay">{error}</p>}
      </div>
      <div className="flex justify-end gap-2 border-t border-bne-line px-6 py-4">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} loading={busy}>Upload</Button>
      </div>
    </Modal>
  )
}

export function EstimateNetworkModal({ isOpen, onClose, onDone }: NetworkIntakeModalProps) {
  const [assets, setAssets] = useState('{\n  "BANK_A": 120.0,\n  "BANK_B": 80.0\n}')
  const [liabilities, setLiabilities] = useState('{\n  "BANK_A": 110.0,\n  "BANK_B": 90.0\n}')
  const [result, setResult] = useState<NetworkEstimateResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const payload = {
        interbank_assets: JSON.parse(assets) as Record<string, number>,
        interbank_liabilities: JSON.parse(liabilities) as Record<string, number>
      }
      const response = await fetchApi<NetworkEstimateResult>('/v1/network/estimate', {
        method: 'POST',
        body: JSON.stringify(payload)
      })
      setResult(response)
      onDone?.(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The estimate was refused.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Estimate a network from declared marginals" widthClass="max-w-xl">
      <div className="space-y-4 px-6 py-5">
        <p className="text-sm text-bne-muted">
          When the matrix does not exist but the totals do: declare each
          institution's total interbank claims and obligations (from published
          aggregates, e.g. call reports). The maximum-entropy estimator
          completes them to a bilateral matrix -- the least-informative matrix
          consistent with the totals, and labelled as an estimate everywhere.
        </p>
        <label className="block text-sm">
          <span className="text-bne-ink font-medium">Interbank assets (claims), JSON</span>
          <textarea
            rows={4}
            className="mt-1 w-full rounded-lg border border-bne-line px-3 py-2 font-mono text-xs focus:border-bne-pine focus:outline-none"
            value={assets}
            onChange={(event) => setAssets(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-bne-ink font-medium">Interbank liabilities (obligations), JSON</span>
          <textarea
            rows={4}
            className="mt-1 w-full rounded-lg border border-bne-line px-3 py-2 font-mono text-xs focus:border-bne-pine focus:outline-none"
            value={liabilities}
            onChange={(event) => setLiabilities(event.target.value)}
          />
        </label>
        {result && (
          <p className="text-xs text-bne-muted">
            {result.n_links ?? result.edges?.length ?? 0} link(s) via {result.method}. {result.uncertainty}
          </p>
        )}
        {error && <p className="text-sm text-bne-clay">{error}</p>}
      </div>
      <div className="flex justify-end gap-2 border-t border-bne-line px-6 py-4">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={submit} loading={busy}>Estimate</Button>
      </div>
    </Modal>
  )
}
