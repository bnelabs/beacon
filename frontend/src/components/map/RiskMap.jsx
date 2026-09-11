import { useCallback, useEffect, useMemo, useState } from 'react'
import DeckGL from '@deck.gl/react'
import { MapView } from '@deck.gl/core'
import { ArcLayer, BitmapLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { TileLayer } from '@deck.gl/geo-layers'
import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import MapLegend from './MapLegend'
import { getRiskColor, networkConnections } from '../../data/network-connections'
import { regions } from '../../data/regions'
import regionBoundaries from '../../data/region-boundaries.json'

const BASEMAP_URL = 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
const MAX_EXPOSURE = 312_000_000_000
const MAX_BANK_POINTS = 500

const INITIAL_VIEW_STATE = {
  longitude: 8,
  latitude: 20,
  zoom: 1,
  pitch: 0,
  bearing: 0,
  minZoom: 0.6,
  maxZoom: 12
}

const HEAT_COLOR_RANGE = [
  [29, 78, 216, 0],
  [16, 185, 129, 120],
  [245, 158, 11, 180],
  [220, 38, 38, 230]
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
  resetToken = 0
}) {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE)

  useEffect(() => {
    setViewState(INITIAL_VIEW_STATE)
  }, [resetToken])

  const riskByRegion = useMemo(() => {
    const totals = {}
    for (const connection of networkConnections) {
      for (const regionId of [connection.source, connection.target]) {
        const entry = totals[regionId] || (totals[regionId] = { sum: 0, count: 0, max: 0 })
        entry.sum += connection.riskScore
        entry.count += 1
        entry.max = Math.max(entry.max, connection.riskScore)
      }
    }

    return Object.fromEntries(
      regions.map((region) => {
        const entry = totals[region.id]
        if (!entry) return [region.id, 0.35]
        const blended = (entry.sum / entry.count) * 0.6 + entry.max * 0.4
        return [region.id, Number(blended.toFixed(3))]
      })
    )
  }, [])

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
        risk: riskByRegion[region.id] ?? 0.35
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
      networkConnections
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
    []
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

  const baseLayer = useMemo(
    () =>
      new TileLayer({
        id: 'basemap',
        data: BASEMAP_URL,
        minZoom: 0,
        maxZoom: 19,
        tileSize: 256,
        // Tile errors are expected when offline; keep them out of the console.
        onTileError: () => {},
        renderSubLayers: (props) => {
          const { west, south, east, north } = props.tile.bbox
          return new BitmapLayer(props, {
            data: null,
            image: props.data,
            bounds: [west, south, east, north]
          })
        }
      }),
    []
  )

  const selectedIso3 = selectedRegion?.iso3

  const layers = useMemo(() => {
    const stack = [
      baseLayer,
      new GeoJsonLayer({
        id: 'region-boundaries',
        data: regionBoundaries,
        stroked: true,
        filled: true,
        pickable: true,
        getFillColor: (feature) =>
          feature.properties.iso3 === selectedIso3 ? [0, 102, 204, 70] : [15, 23, 42, 40],
        getLineColor: (feature) =>
          feature.properties.iso3 === selectedIso3 ? [147, 197, 253, 255] : [96, 165, 250, 110],
        getLineWidth: (feature) => (feature.properties.iso3 === selectedIso3 ? 2 : 1),
        lineWidthUnits: 'pixels',
        updateTriggers: {
          getFillColor: selectedIso3,
          getLineColor: selectedIso3,
          getLineWidth: selectedIso3
        }
      })
    ]

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
          getSourceColor: (arc) => riskColor(arc.riskScore, 230),
          getTargetColor: (arc) => riskColor(arc.riskScore, 80),
          getWidth: (arc) => 1 + (arc.exposure / MAX_EXPOSURE) * 4,
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
        getFillColor: (point) => riskColor(point.risk, 200),
        getLineColor: [15, 23, 42, 220],
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
          getFillColor: (point) => riskColor(point.risk, 210),
          getLineColor: [248, 250, 252, 180],
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
          getLineColor: [255, 255, 255, 235],
          getLineWidth: 3
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
        getColor: [226, 232, 240, 230],
        getPixelOffset: [0, 16],
        getTextAnchor: 'middle',
        getAlignmentBaseline: 'top',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontWeight: 600,
        outlineWidth: 2,
        outlineColor: [15, 23, 42, 220]
      })
    )

    return stack
  }, [
    arcs,
    bankPoints,
    baseLayer,
    heatPoints,
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
      className="relative h-full w-full overflow-hidden rounded-2xl bg-[#0b1120]"
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
        className="pointer-events-none absolute bottom-0 left-0 z-10 rounded-tr-lg bg-slate-950/70 px-2 py-1 text-[10px] text-slate-300"
      >
        © OpenStreetMap contributors © CARTO
      </div>
    </div>
  )
}
