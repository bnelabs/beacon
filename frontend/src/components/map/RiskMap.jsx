import { useCallback, useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { MapView } from '@deck.gl/core'
import { ArcLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import MapLegend from './MapLegend'
import { getRiskColor, networkConnections } from '../../data/network-connections'
import { normalizeNetworkGraph, useNetworkGraph } from '../../hooks/useApi'
import { regions } from '../../data/regions'

// The Natural Earth basemap (world-countries.json) and the region boundaries
// (region-boundaries.json) are ~190 KB static GeoJSON payloads each. They are
// lazy-loaded with dynamic import() inside the component (see the geo effect
// below) so Vite splits them into separate on-demand chunks instead of inlining
// ~370 KB of geography into the primary dashboard bundle. Natural Earth is
// public domain; at 1:110m it is context, not detail -- the markers, heat and
// arcs are the content of this map. A raster tile service was rejected: the
// keyless CARTO endpoint now answers with tiles watermarked "API KEY REQUIRED"
// diagonally across the map, and any tile CDN is a third-party runtime
// dependency plus an offline failure mode (an earlier README capture showed a
// blank sea where the basemap never loaded).

// Visual placeholder for a region with no scored corridor. It is a colour input,
// not a financial figure: a risk score is never invented for an exposure that
// has none, but the marker still has to be drawn.
const NEUTRAL_REGION_RISK = 0.35

// Neutral arc colour used when the API reports no risk score for an edge.
// Painting an unscored exposure with a "low risk" green would assert something
// the data does not say.
const UNSCORED_ARC_COLOR = [138, 129, 104]

const MAX_BANK_POINTS = 500

const INITIAL_VIEW_STATE = {
  longitude: 8,
  latitude: 20,
  zoom: 1,
  pitch: 0,
  bearing: 0,
  minZoom: 0.6,
  maxZoom: 6
}

const HEAT_COLOR_RANGE = [
  [103, 133, 79, 0],
  [103, 133, 79, 100],
  [194, 154, 51, 160],
  [192, 95, 44, 205],
  [138, 51, 32, 235]
]

const MAP_VIEW = new MapView({ id: 'risk-map-view', controller: true, repeat: true })

const regionById = Object.fromEntries(regions.map((region) => [region.id, region]))
const regionByIso3 = Object.fromEntries(regions.map((region) => [region.iso3, region]))

function hexToRgb(hex) {
  const value = Number.parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function riskColor(score, alpha) {
  return [...hexToRgb(getRiskColor(score)), alpha]
}

function seededUnit(seed) {
  const value = Math.sin(seed * 12.9898) * 43758.5453
  return value - Math.floor(value)
}

function regionPointRadius(point) {
  return 4 + Math.sqrt(point.bankCount || 1) * 0.35 + point.risk * 4
}

export default function RiskMap({
  selectedRegion,
  onRegionSelect,
  showNetwork = false,
  showHeatmap = true,
  banks = [],
  onConnectionClick,
  resetToken = 0,
  allowStaticNetworkFallback = false
}) {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE)

  useEffect(() => {
    setViewState(INITIAL_VIEW_STATE)
  }, [resetToken])

  // Static geography lives in two large JSON files that are code-split into
  // their own chunks and fetched on mount rather than shipped in the main
  // bundle. Until they resolve the map renders markers/heat/arcs over a plain
  // background, so first paint is not blocked on ~370 KB of polygons.
  const [geo, setGeo] = useState({ worldCountries: null, regionBoundaries: null })

  useEffect(() => {
    let cancelled = false
    Promise.all([
      import('../../data/world-countries.json'),
      import('../../data/region-boundaries.json')
    ])
      .then(([world, bounds]) => {
        if (!cancelled) {
          setGeo({ worldCountries: world.default, regionBoundaries: bounds.default })
        }
      })
      .catch(() => {
        // Geography is context, not content: if a chunk fails to load the map
        // still renders its data layers; the basemap simply stays absent.
        if (!cancelled) {
          setGeo((current) => current)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const {
    data: networkPayload,
    isLoading: networkLoading,
    isError: networkIsError
  } = useNetworkGraph()

  const network = useMemo(() => normalizeNetworkGraph(networkPayload), [networkPayload])

  // The bundled file is demo data. It is only ever rendered when the caller
  // explicitly opts in AND the backend has nothing to serve; the opt-in path is
  // surfaced in the UI so it cannot be mistaken for a live network.
  const fallbackActive = Boolean(
    allowStaticNetworkFallback &&
      !networkLoading &&
      (networkIsError || network.status === 'unavailable') &&
      networkConnections.length > 0
  )

  const connections = useMemo(() => {
    if (network.status === 'available') {
      return network.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        exposure: Number(edge.exposure),
        riskScore: typeof edge.risk_score === 'number' ? edge.risk_score : null,
        layer: edge.layer,
        kind: edge.kind
      }))
    }
    if (fallbackActive) {
      return networkConnections.map((connection) => ({
        ...connection,
        riskScore: typeof connection.riskScore === 'number' ? connection.riskScore : null
      }))
    }
    return []
  }, [network, fallbackActive])

  const maxExposure = useMemo(
    () => connections.reduce((max, connection) => Math.max(max, connection.exposure || 0), 0) || 1,
    [connections]
  )

  const riskByRegion = useMemo(() => {
    const totals = {}
    for (const connection of connections) {
      for (const regionId of [connection.source, connection.target]) {
        const entry = totals[regionId] || (totals[regionId] = { sum: 0, count: 0, max: 0 })
        if (typeof connection.riskScore !== 'number') continue
        entry.sum += connection.riskScore
        entry.count += 1
        entry.max = Math.max(entry.max, connection.riskScore)
      }
    }

    return Object.fromEntries(
      regions.map((region) => {
        const entry = totals[region.id]
        if (!entry || entry.count === 0) return [region.id, NEUTRAL_REGION_RISK]
        const blended = (entry.sum / entry.count) * 0.6 + entry.max * 0.4
        return [region.id, Number(blended.toFixed(3))]
      })
    )
  }, [connections])

  const regionPoints = useMemo(
    () =>
      regions.map((region) => ({
        kind: 'region',
        id: region.id,
        name: region.name,
        country: region.country,
        bankCount: region.bankCount,
        regionId: region.id,
        position: [region.lon, region.lat],
        risk: riskByRegion[region.id] ?? NEUTRAL_REGION_RISK
      })),
    [riskByRegion]
  )

  const bankPoints = useMemo(() => {
    if (!selectedRegion || !banks?.length) return []

    return banks.slice(0, MAX_BANK_POINTS).map((bank, index) => {
      const seed = Number(bank.id) || index + 1
      const angle = seededUnit(seed * 1.37 + index) * Math.PI * 2
      const distance = 0.4 + seededUnit(seed * 7.13 + index * 2) * 2.2
      const parsed = Number(bank.risk_score)

      return {
        kind: 'bank',
        id: bank.id ?? `${selectedRegion.id}-${index}`,
        name: bank.name,
        regionId: selectedRegion.id,
        position: [
          selectedRegion.lon + Math.cos(angle) * distance,
          selectedRegion.lat + Math.sin(angle) * distance
        ],
        risk: Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1) : 0.5
      }
    })
  }, [banks, selectedRegion])

  const arcs = useMemo(
    () =>
      connections
        .map((connection) => {
          const source = regionById[connection.source]
          const target = regionById[connection.target]
          if (!source || !target) return null
          return {
            ...connection,
            kind: 'connection',
            sourcePosition: [source.lon, source.lat],
            targetPosition: [target.lon, target.lat]
          }
        })
        .filter(Boolean),
    [connections]
  )

  const heatPoints = useMemo(() => {
    if (!bankPoints.length) return regionPoints
    return [
      ...regionPoints.filter((point) => point.regionId !== selectedRegion?.id),
      ...bankPoints
    ]
  }, [bankPoints, regionPoints, selectedRegion])

  const scatterRegionPoints = useMemo(() => {
    if (!bankPoints.length) return regionPoints
    return regionPoints.filter((point) => point.regionId !== selectedRegion?.id)
  }, [bankPoints, regionPoints, selectedRegion])

  const baseLayer = useMemo(() => {
    if (!geo.worldCountries) return null
    return new GeoJsonLayer({
      id: 'world-land',
      data: geo.worldCountries,
      stroked: true,
      filled: true,
      pickable: false,
      getFillColor: [246, 242, 233],
      getLineColor: [211, 203, 182],
      getLineWidth: 0.6,
      lineWidthUnits: 'pixels'
    })
  }, [geo.worldCountries])

  const selectedIso3 = selectedRegion?.iso3

  const layers = useMemo(() => {
    const stack = []
    if (baseLayer) stack.push(baseLayer)
    if (geo.regionBoundaries) {
      stack.push(
        new GeoJsonLayer({
          id: 'region-boundaries',
          data: geo.regionBoundaries,
          stroked: true,
          filled: true,
          pickable: true,
          getFillColor: (feature) =>
            feature.properties.iso3 === selectedIso3 ? [44, 85, 69, 46] : [110, 102, 83, 14],
          getLineColor: (feature) =>
            feature.properties.iso3 === selectedIso3 ? [44, 85, 69, 255] : [110, 102, 83, 105],
          getLineWidth: (feature) => (feature.properties.iso3 === selectedIso3 ? 2 : 1),
          lineWidthUnits: 'pixels',
          updateTriggers: {
            getFillColor: selectedIso3,
            getLineColor: selectedIso3,
            getLineWidth: selectedIso3
          }
        })
      )
    }

    if (showHeatmap) {
      stack.push(
        new HeatmapLayer({
          id: 'liquidity-heatmap',
          data: heatPoints,
          getPosition: (point) => point.position,
          getWeight: (point) => (point.kind === 'bank' ? point.risk : point.risk * point.bankCount),
          radiusPixels: 60,
          intensity: 1,
          threshold: 0.03,
          aggregation: 'SUM',
          colorRange: HEAT_COLOR_RANGE,
          pickable: false
        })
      )
    }

    if (showNetwork) {
      stack.push(
        new ArcLayer({
          id: 'interbank-exposures',
          data: arcs,
          greatCircle: true,
          pickable: true,
          getSourcePosition: (arc) => arc.sourcePosition,
          getTargetPosition: (arc) => arc.targetPosition,
          getSourceColor: (arc) =>
            arc.riskScore == null ? [...UNSCORED_ARC_COLOR, 230] : riskColor(arc.riskScore, 230),
          getTargetColor: (arc) =>
            arc.riskScore == null ? [...UNSCORED_ARC_COLOR, 80] : riskColor(arc.riskScore, 80),
          getWidth: (arc) => 1 + (arc.exposure / maxExposure) * 4,
          widthUnits: 'pixels',
          getHeight: 0.35,
          updateTriggers: {
            getSourceColor: showNetwork,
            getTargetColor: showNetwork
          }
        })
      )
    }

    stack.push(
      new ScatterplotLayer({
        id: 'region-markers',
        data: scatterRegionPoints,
        pickable: true,
        stroked: true,
        filled: true,
        radiusUnits: 'pixels',
        lineWidthUnits: 'pixels',
        getPosition: (point) => point.position,
        getRadius: regionPointRadius,
        getFillColor: (point) => riskColor(point.risk, 215),
        getLineColor: [252, 250, 244, 235],
        getLineWidth: 1.5
      })
    )

    if (bankPoints.length) {
      stack.push(
        new ScatterplotLayer({
          id: 'bank-markers',
          data: bankPoints,
          pickable: true,
          stroked: true,
          filled: true,
          radiusUnits: 'pixels',
          lineWidthUnits: 'pixels',
          getPosition: (point) => point.position,
          getRadius: (point) => 3.5 + point.risk * 9,
          getFillColor: (point) => riskColor(point.risk, 225),
          getLineColor: [252, 250, 244, 210],
          getLineWidth: 1
        })
      )
    }

    if (selectedRegion) {
      stack.push(
        new ScatterplotLayer({
          id: 'selected-region',
          data: [selectedRegion],
          pickable: false,
          stroked: true,
          filled: false,
          radiusUnits: 'pixels',
          lineWidthUnits: 'pixels',
          getPosition: (region) => [region.lon, region.lat],
          getRadius: (region) =>
            regionPointRadius({ bankCount: region.bankCount, risk: riskByRegion[region.id] ?? 0.35 }) + 5,
          getLineColor: [38, 33, 26, 235],
          getLineWidth: 2.5
        })
      )
    }

    stack.push(
      new TextLayer({
        id: 'region-labels',
        data: scatterRegionPoints,
        pickable: false,
        getPosition: (point) => point.position,
        getText: (point) => point.name,
        getSize: 11,
        getColor: [38, 33, 26, 235],
        getPixelOffset: [0, 16],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'top',
        fontFamily: 'ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif',
        fontWeight: 600,
        outlineWidth: 2,
        outlineColor: [246, 242, 233, 235]
      })
    )

    return stack
  }, [
    arcs,
    bankPoints,
    baseLayer,
    geo.regionBoundaries,
    heatPoints,
    maxExposure,
    riskByRegion,
    scatterRegionPoints,
    selectedIso3,
    selectedRegion,
    showHeatmap,
    showNetwork
  ])

  const handleClick = useCallback(
    (info) => {
      const picked = info?.object
      if (!picked) return
      if (picked.kind === 'connection') {
        onConnectionClick?.(picked)
        return
      }
      if (picked.kind === 'bank' || picked.kind === 'region') {
        onRegionSelect?.(regionById[picked.regionId])
        return
      }
      const iso3 = picked.properties?.iso3
      if (iso3 && regionByIso3[iso3]) {
        onRegionSelect?.(regionByIso3[iso3])
      }
    },
    [onConnectionClick, onRegionSelect]
  )

  const handleViewStateChange = useCallback(({ viewState: next }) => {
    setViewState((previous) => ({ ...previous, ...next }))
  }, [])

  return (
    <div
      data-testid="risk-map"
      aria-label="Systemic liquidity risk map"
      className="relative h-full w-full overflow-hidden rounded-md border border-bne-line bg-bne-paper-dim"
    >
      <DeckGL
        views={MAP_VIEW}
        viewState={viewState}
        onViewStateChange={handleViewStateChange}
        controller
        layers={layers}
        onClick={handleClick}
        getCursor={({ isDragging, isHovering }) => (isDragging ? 'grabbing' : isHovering ? 'pointer' : 'grab')}
      />

      <MapLegend showNetwork={showNetwork} className="absolute right-4 top-4 z-10" />

      <div
        data-testid="map-attribution"
        className="pointer-events-none absolute bottom-0 left-0 z-10 rounded-tr-md bg-bne-card/85 border-r border-t border-bne-line px-2 py-1 text-[10px] text-bne-faint"
      >
        Boundaries: Natural Earth (public domain)
      </div>
    </div>
  )
}
