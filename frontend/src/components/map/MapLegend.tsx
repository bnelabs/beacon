import { cn } from '../../utils/cn'
import { getRiskColor, RISK_COLORS } from '../../data/network-connections'

interface RiskBand {
  label: string
  range: string
  sample: number
}

const RISK_BANDS: RiskBand[] = [
  { label: 'Low', range: '< 0.30', sample: 0.15 },
  { label: 'Medium', range: '0.30 – 0.59', sample: 0.45 },
  { label: 'High', range: '0.60 – 0.79', sample: 0.7 },
  { label: 'Critical', range: '≥ 0.80', sample: 0.9 }
]

export interface MapLegendProps {
  showNetwork?: boolean
  className?: string
}

export default function MapLegend({ showNetwork = false, className }: MapLegendProps) {
  return (
    <div
      data-testid="map-legend"
      className={cn(
        'w-52 rounded-md border border-bne-line bg-bne-card/95 p-3 text-xs shadow-bne-panel',
        className
      )}
    >
      <p className="bne-micro mb-2">Risk Score</p>
      <ul className="space-y-1.5">
        {RISK_BANDS.map((band) => (
          <li key={band.label} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-bne-ink-soft">
              <span
                className="h-2.5 w-2.5 rounded-[2px]"
                style={{ backgroundColor: getRiskColor(band.sample) }}
              />
              {band.label}
            </span>
            <span className="font-mono text-[10px] tnum text-bne-faint">{band.range}</span>
          </li>
        ))}
        <li className="flex items-center justify-between gap-3 pt-0.5">
          <span className="flex items-center gap-2 text-bne-faint">
            <span
              className="h-2.5 w-2.5 rounded-[2px] border border-dashed border-bne-line-strong"
              style={{ backgroundColor: 'transparent' }}
            />
            Uncalibrated
          </span>
          <span className="font-mono text-[10px] text-bne-faint">no level</span>
        </li>
      </ul>

      <div className="mt-3 border-t border-bne-line-soft pt-3">
        <p className="bne-micro mb-1.5">Liquidity Heat</p>
        <div
          className="h-2 rounded-[2px]"
          style={{
            background: `linear-gradient(90deg, ${RISK_COLORS.low} 0%, ${RISK_COLORS.medium} 45%, ${RISK_COLORS.high} 75%, ${RISK_COLORS.critical} 100%)`
          }}
        />
        <div className="mt-1 flex justify-between text-[10px] text-bne-faint">
          <span>Low</span>
          <span>High</span>
        </div>
      </div>

      {showNetwork && (
        <div className="mt-3 border-t border-bne-line-soft pt-3 text-[11px] text-bne-muted">
          <p className="bne-micro mb-1">Interbank Exposures</p>
          <p>Arc width scales with exposure</p>
          <p>Arc colour reflects counterparty risk</p>
        </div>
      )}

      <p className="mt-3 text-[10px] leading-snug text-bne-faint">
        Marker radius scales with risk score and institution count.
      </p>
    </div>
  )
}
