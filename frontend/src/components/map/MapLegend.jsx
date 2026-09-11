import { cn } from '../../utils/cn'
import { getRiskColor } from '../../data/network-connections'

const RISK_BANDS = [
  { label: 'Low', range: '< 0.30', sample: 0.15 },
  { label: 'Medium', range: '0.30 – 0.59', sample: 0.45 },
  { label: 'High', range: '0.60 – 0.79', sample: 0.7 },
  { label: 'Critical', range: '≥ 0.80', sample: 0.9 }
]

export default function MapLegend({ showNetwork = false, className }) {
  return (
    <div
      data-testid="map-legend"
      className={cn(
        'w-48 rounded-xl border border-bne-frost bg-white/95 p-3 text-xs shadow-bne-panel backdrop-blur-sm',
        className
      )}
    >
      <p className="mb-2 font-semibold text-bne-ink">Risk Score</p>
      <ul className="space-y-1.5">
        {RISK_BANDS.map((band) => (
          <li key={band.label} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-bne-steel">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: getRiskColor(band.sample) }}
              />
              {band.label}
            </span>
            <span className="font-mono text-[10px] text-bne-steel">{band.range}</span>
          </li>
        ))}
      </ul>

      <div className="mt-3 border-t border-bne-frost pt-3">
        <p className="mb-1.5 font-semibold text-bne-ink">Liquidity Heat</p>
        <div
          className="h-2 rounded-full"
          style={{ background: 'linear-gradient(90deg, #1D4ED8 0%, #10B981 40%, #F59E0B 70%, #DC2626 100%)' }}
        />
        <div className="mt-1 flex justify-between text-[10px] text-bne-steel">
          <span>Low</span>
          <span>High</span>
        </div>
      </div>

      {showNetwork && (
        <div className="mt-3 border-t border-bne-frost pt-3 text-[11px] text-bne-steel">
          <p className="mb-1 font-semibold text-bne-ink">Interbank Exposures</p>
          <p>Arc width scales with exposure</p>
          <p>Arc colour reflects counterparty risk</p>
        </div>
      )}

      <p className="mt-3 text-[10px] leading-snug text-bne-steel/80">
        Marker radius scales with risk score and institution count.
      </p>
    </div>
  )
}
