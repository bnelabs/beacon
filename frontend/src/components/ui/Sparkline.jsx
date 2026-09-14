/**
 * Dependency-free SVG sparkline / area chart in the house style:
 * ink-soft stroke, pine or clay accent, hairline baseline, tabular tooltips
 * via <title>. No chart library: the dashboard must render in air-gapped
 * deployments and in the sandboxed docs preview alike.
 */
export default function Sparkline({
  values,
  width = 120,
  height = 32,
  tone = 'pine',
  fill = true,
  ariaLabel
}) {
  const points = (values || []).map(Number).filter((v) => Number.isFinite(v))
  if (points.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true">
        <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="#E2DAC8" strokeWidth="1" />
      </svg>
    )
  }

  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const step = width / (points.length - 1)
  const coords = points.map((value, index) => [
    index * step,
    height - 3 - ((value - min) / span) * (height - 8)
  ])
  const path = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${path} L${width},${height - 1} L0,${height - 1} Z`
  const stroke = tone === 'clay' ? '#A33D22' : tone === 'ochre' ? '#A87C1D' : '#2C5545'
  const fillColour = tone === 'clay' ? 'rgba(163,61,34,0.10)' : tone === 'ochre' ? 'rgba(168,124,29,0.10)' : 'rgba(44,85,69,0.10)'
  const last = coords[coords.length - 1]

  return (
    <svg width={width} height={height} role="img" aria-label={ariaLabel || 'trend'}>
      {fill && <path d={area} fill={fillColour} stroke="none" />}
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill={stroke} />
      <line x1="0" y1={height - 1} x2={width} y2={height - 1} stroke="#E2DAC8" strokeWidth="1" />
    </svg>
  )
}
