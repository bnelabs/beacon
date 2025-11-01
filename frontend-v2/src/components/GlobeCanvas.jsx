import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars, useTexture } from '@react-three/drei'
import { Suspense, useEffect, useMemo, useRef, useState, useCallback, memo } from 'react'
import { useUIStore } from '../state/uiStore.js'
import { REGION_DEFINITIONS, REGION_LOOKUP } from '../config/regions.js'
import * as THREE from 'three'
import { geoDistance, geoInterpolate, geoArea } from 'd3-geo'
import GeoJsonGeometry from 'three-geojson-geometry'
import { feature } from 'topojson-client'
import earthDayMap from '../assets/globe/earth-day.jpg'
import earthBumpMap from '../assets/globe/earth-topology.png'
import earthNightMap from '../assets/globe/earth-night.jpg'
import earcut from 'earcut'

// Ensure earcut is available for three-geojson-geometry internals.
if (typeof globalThis !== 'undefined' && !globalThis.earcut) {
  globalThis.earcut = earcut
}

const BASE_RADIUS = 1.6
const DEFAULT_CAMERA_POSITION = new THREE.Vector3(0, 0, 4.2)
const DEFAULT_TARGET = new THREE.Vector3(0, 0, 0)
const REGION_FILL_ALTITUDE = BASE_RADIUS + 0.018
const REGION_OUTLINE_ALTITUDE = BASE_RADIUS + 0.026
const COUNTRY_FILL_ALTITUDE = BASE_RADIUS + 0.03
const COUNTRY_OUTLINE_ALTITUDE = BASE_RADIUS + 0.038
const INTERPOLATION_MAX_DEG = 0.75
const MIN_POLYGON_AREA = 2e-5
const GEOJSON_RESOLUTION = Math.max(2, Math.round(5 / INTERPOLATION_MAX_DEG))
const MANUAL_OVERRIDE_MS = 4500
const FOCUS_RESUME_DELAY_MS = 3000

// Lazy-load GeoJSON data - don't block module initialization
let countriesTopology = null
let COUNTRY_FEATURES = null
let COUNTRIES_BY_NAME = null

async function loadGeoData() {
  if (COUNTRY_FEATURES) return { COUNTRY_FEATURES, COUNTRIES_BY_NAME }

  const topology = await import('../assets/geo/countries-50m.json')
  countriesTopology = topology.default || topology
  COUNTRY_FEATURES = feature(countriesTopology, countriesTopology.objects.countries).features
  COUNTRIES_BY_NAME = new Map(COUNTRY_FEATURES.map((feature) => [feature.properties.name, feature]))

  return { COUNTRY_FEATURES, COUNTRIES_BY_NAME }
}

function latLongToVector(lat, lon, radius) {
  const phi = THREE.MathUtils.degToRad(90 - lat)
  const theta = THREE.MathUtils.degToRad(lon + 180)

  const x = -radius * Math.sin(phi) * Math.cos(theta)
  const z = radius * Math.sin(phi) * Math.sin(theta)
  const y = radius * Math.cos(phi)

  return new THREE.Vector3(x, y, z)
}

const GlobeSurface = memo(function GlobeSurface() {
  const [colorMap, elevationMap, nightMap] = useTexture([earthDayMap, earthBumpMap, earthNightMap])

  useEffect(() => {
    colorMap.colorSpace = THREE.SRGBColorSpace
    nightMap.colorSpace = THREE.SRGBColorSpace
    colorMap.anisotropy = 16
    elevationMap.anisotropy = 8
    nightMap.anisotropy = 8
  }, [colorMap, elevationMap, nightMap])

  return (
    <>
      <mesh>
        <sphereGeometry args={[BASE_RADIUS, 256, 256]} />
        <meshStandardMaterial
          map={colorMap}
          bumpMap={elevationMap}
          bumpScale={0.035}
          metalness={0.15}
          roughness={0.85}
          emissive="#0f172a"
          emissiveIntensity={0.25}
          emissiveMap={nightMap}
        />
      </mesh>
      <mesh>
        <sphereGeometry args={[BASE_RADIUS + 0.02, 256, 256]} />
        <meshBasicMaterial
          color="#4EA8DE"
          transparent
          opacity={0.12}
          side={THREE.BackSide}
          depthWrite={false}
        />
      </mesh>
    </>
  )
})

function wrapLongitude(lon) {
  const normalized = ((lon + 180) % 360 + 360) % 360 - 180
  return normalized === -180 ? 180 : normalized
}

function densifyLine(line, maxDeg = INTERPOLATION_MAX_DEG) {
  if (!Array.isArray(line) || line.length === 0) {
    return []
  }

  const result = []
  let previous = null

  line.forEach((point) => {
    if (!point) {
      return
    }
    if (previous) {
      const distance = (geoDistance(previous, point) * 180) / Math.PI
      if (distance > maxDeg) {
        const interpolate = geoInterpolate(previous, point)
        const steps = Math.ceil(distance / maxDeg)
        for (let step = 1; step < steps; step += 1) {
          const t = step / steps
          const [lon, lat] = interpolate(t)
          result.push([wrapLongitude(lon), lat])
        }
      }
    }
    result.push([wrapLongitude(point[0]), point[1]])
    previous = point
  })

  return result
}

function normalizeRing(ring) {
  const densified = densifyLine(ring)
  if (densified.length === 0) {
    return []
  }

  const cleaned = densified.filter((point, index, arr) => {
    if (index === 0) return true
    const prev = arr[index - 1]
    return Math.abs(point[0] - prev[0]) > 1e-6 || Math.abs(point[1] - prev[1]) > 1e-6
  })

  if (cleaned.length > 1) {
    const first = cleaned[0]
    const last = cleaned[cleaned.length - 1]
    if (Math.abs(first[0] - last[0]) < 1e-6 && Math.abs(first[1] - last[1]) < 1e-6) {
      cleaned.pop()
    }
  }
  return cleaned
}

function buildRegionMeshes(countriesByName) {
  const meshes = new Map()

  REGION_DEFINITIONS.forEach((region) => {
    const aggregatedPolygons = []

    region.countryNames.forEach((countryName) => {
      const countryFeature = countriesByName.get(countryName)
      if (!countryFeature) {
        return
      }

      const polygons =
        countryFeature.geometry.type === 'Polygon'
          ? [countryFeature.geometry.coordinates]
          : countryFeature.geometry.coordinates

      polygons
        .map((polygon) => ({
          polygon,
          area: geoArea({ type: 'Polygon', coordinates: polygon })
        }))
        .filter((entry) => entry.area >= MIN_POLYGON_AREA)
        .forEach((entry) => aggregatedPolygons.push(entry.polygon))
    })

    if (aggregatedPolygons.length === 0) {
      return
    }

    const geoJson = {
      type: 'MultiPolygon',
      coordinates: aggregatedPolygons
    }

    const fillGeometry = new GeoJsonGeometry(geoJson, REGION_FILL_ALTITUDE, GEOJSON_RESOLUTION)
    fillGeometry.computeVertexNormals()

    const outlineGeometries = []
    aggregatedPolygons.forEach((polygon) => {
      polygon.forEach((ring) => {
        const points = normalizeRing(ring)
        if (points.length < 2) {
          return
        }
        const outlinePositions = new Float32Array((points.length + 1) * 3)
        points.forEach(([lon, lat], idx) => {
          const position = latLongToVector(lat, lon, REGION_OUTLINE_ALTITUDE)
          outlinePositions[idx * 3] = position.x
          outlinePositions[idx * 3 + 1] = position.y
          outlinePositions[idx * 3 + 2] = position.z
        })
        const first = latLongToVector(points[0][1], points[0][0], REGION_OUTLINE_ALTITUDE)
        outlinePositions[outlinePositions.length - 3] = first.x
        outlinePositions[outlinePositions.length - 2] = first.y
        outlinePositions[outlinePositions.length - 1] = first.z

        const outlineGeometry = new THREE.BufferGeometry()
        outlineGeometry.setAttribute('position', new THREE.BufferAttribute(outlinePositions, 3))
        outlineGeometry.computeBoundingSphere()
        outlineGeometries.push(outlineGeometry)
      })
    })

    meshes.set(region.id, { fillGeometry, outlineGeometries })
  })

  return meshes
}

function buildCountryMeshes(countryFeatures) {
  const meshes = new Map()

  countryFeatures.forEach((feature) => {
    const polygons =
      feature.geometry.type === 'Polygon'
        ? [feature.geometry.coordinates]
        : feature.geometry.coordinates

    const filteredPolygons = polygons
      .map((polygon) => ({ polygon, area: geoArea({ type: 'Polygon', coordinates: polygon }) }))
      .filter((entry) => entry.area >= MIN_POLYGON_AREA / 10)

    if (filteredPolygons.length === 0) {
      return
    }

    const geoJson = {
      type: 'MultiPolygon',
      coordinates: filteredPolygons.map((entry) => entry.polygon)
    }

    const fillGeometry = new GeoJsonGeometry(geoJson, COUNTRY_FILL_ALTITUDE, GEOJSON_RESOLUTION)
    fillGeometry.computeVertexNormals()

    const outlineGeometries = []
    filteredPolygons.forEach((entry) => {
      entry.polygon.forEach((ring) => {
        const points = normalizeRing(ring)
        if (points.length < 2) {
          return
        }
        const outlinePositions = new Float32Array((points.length + 1) * 3)
        points.forEach(([lon, lat], idx) => {
          const position = latLongToVector(lat, lon, COUNTRY_OUTLINE_ALTITUDE)
          outlinePositions[idx * 3] = position.x
          outlinePositions[idx * 3 + 1] = position.y
          outlinePositions[idx * 3 + 2] = position.z
        })
        const first = latLongToVector(points[0][1], points[0][0], COUNTRY_OUTLINE_ALTITUDE)
        outlinePositions[outlinePositions.length - 3] = first.x
        outlinePositions[outlinePositions.length - 2] = first.y
        outlinePositions[outlinePositions.length - 1] = first.z

        const outlineGeometry = new THREE.BufferGeometry()
        outlineGeometry.setAttribute('position', new THREE.BufferAttribute(outlinePositions, 3))
        outlineGeometry.computeBoundingSphere()
        outlineGeometries.push(outlineGeometry)
      })
    })

    meshes.set(feature.properties.name, { fillGeometry, outlineGeometries })
  })

  return meshes
}

const RegionOverlay = memo(function RegionOverlay({ region, meshData }) {
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const toggleRegion = useUIStore((state) => state.toggleRegion)
  const setFocusedRegion = useUIStore((state) => state.setFocusedRegion)
  const focusedRegion = useUIStore((state) => state.focusedRegion)
  const removeCountries = useUIStore((state) => state.removeCountries)
  const [hovered, setHovered] = useState(false)
  const pointerDownRef = useRef(null)
  const draggingRef = useRef(false)

  const isSelected = selectedRegions.includes(region.id)
  const baseColor = useMemo(() => new THREE.Color(region.color), [region.color])

  const fillColor = useMemo(() => {
    const color = baseColor.clone()
    if (isSelected) {
      return color.lerp(new THREE.Color('#ffffff'), 0.35)
    }
    if (hovered) {
      return color.lerp(new THREE.Color('#ffffff'), 0.18)
    }
    return color.multiplyScalar(0.82)
  }, [baseColor, hovered, isSelected])

  const outlineColor = isSelected || hovered ? '#ffffff' : '#C7D2FE'
  const outlineOpacity = isSelected || hovered ? 0.85 : 0.45
  const fillOpacity = isSelected ? 0.65 : hovered ? 0.48 : 0.3

  const handlePointerOver = useCallback((event) => {
    event.stopPropagation()
    if (draggingRef.current) {
      return
    }
    setHovered(true)
    setFocusedRegion(region.id)
    document.body.style.cursor = 'pointer'
  }, [region.id, setFocusedRegion])

  const handlePointerOut = useCallback((event) => {
    event.stopPropagation()
    if (draggingRef.current) {
      return
    }
    setHovered(false)
    if (focusedRegion === region.id) {
      setFocusedRegion(null)
    }
    document.body.style.cursor = ''
  }, [focusedRegion, region.id, setFocusedRegion])

  const handlePointerDown = useCallback((event) => {
    pointerDownRef.current = { x: event.clientX, y: event.clientY }
    draggingRef.current = false
  }, [])

  const handlePointerMove = useCallback((event) => {
    if (!pointerDownRef.current) return
    const dx = event.clientX - pointerDownRef.current.x
    const dy = event.clientY - pointerDownRef.current.y
    if (!draggingRef.current && Math.sqrt(dx * dx + dy * dy) > 4) {
      draggingRef.current = true
    }
  }, [])

  const handlePointerUp = useCallback((event) => {
    if (draggingRef.current) {
      pointerDownRef.current = null
      return
    }
    event.stopPropagation()
    pointerDownRef.current = null
    if (isSelected) {
      removeCountries(region.countryNames)
    }
    toggleRegion(region.id)
  }, [isSelected, region.countryNames, region.id, removeCountries, toggleRegion])

  const handlePointerCancel = useCallback(() => {
    pointerDownRef.current = null
    draggingRef.current = false
  }, [])

  if (!meshData) {
    return null
  }

  return (
    <group>
      <mesh
        geometry={meshData.fillGeometry}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        renderOrder={1}
      >
        <meshStandardMaterial
          color={fillColor}
          transparent
          opacity={fillOpacity}
          depthWrite={false}
          side={THREE.DoubleSide}
          metalness={0.1}
          roughness={0.8}
          polygonOffset
          polygonOffsetFactor={-4}
          polygonOffsetUnits={-2}
        />
      </mesh>
      {meshData.outlineGeometries.map((geometry, index) => (
        <line
          key={`${region.id}-outline-${index}`}
          geometry={geometry}
          onPointerOver={handlePointerOver}
          onPointerOut={handlePointerOut}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          renderOrder={2}
        >
          <lineBasicMaterial color={outlineColor} transparent opacity={outlineOpacity} toneMapped={false} depthTest />
        </line>
      ))}
    </group>
  )
})

const CountryOverlay = memo(function CountryOverlay({ countryName, regionColor, countryMeshes }) {
  const meshData = countryMeshes.get(countryName)
  const selectedCountries = useUIStore((state) => state.selectedCountries)
  const toggleCountry = useUIStore((state) => state.toggleCountry)
  const setFocusedCountry = useUIStore((state) => state.setFocusedCountry)
  const focusedCountry = useUIStore((state) => state.focusedCountry)
  const [hovered, setHovered] = useState(false)
  const pointerDownRef = useRef(null)
  const draggingRef = useRef(false)

  const isSelected = selectedCountries.includes(countryName)
  const baseColor = useMemo(() => new THREE.Color(regionColor || '#38bdf8'), [regionColor])

  const fillColor = useMemo(() => {
    const color = baseColor.clone()
    if (isSelected) {
      return color.lerp(new THREE.Color('#ffffff'), 0.4)
    }
    if (hovered) {
      return color.lerp(new THREE.Color('#e0f2fe'), 0.3)
    }
    return color.multiplyScalar(0.9)
  }, [baseColor, hovered, isSelected])

  const outlineColor = isSelected || hovered ? '#ffffff' : baseColor.clone().offsetHSL(0, -0.2, 0.1).getStyle()
  const outlineOpacity = isSelected || hovered ? 0.9 : 0.55
  const fillOpacity = isSelected ? 0.55 : hovered ? 0.4 : 0.22

  const handlePointerOver = useCallback((event) => {
    event.stopPropagation()
    if (draggingRef.current) {
      return
    }
    setHovered(true)
    setFocusedCountry(countryName)
    document.body.style.cursor = 'pointer'
  }, [countryName, setFocusedCountry])

  const handlePointerOut = useCallback((event) => {
    event.stopPropagation()
    if (draggingRef.current) {
      return
    }
    setHovered(false)
    if (focusedCountry === countryName) {
      setFocusedCountry(null)
    }
    document.body.style.cursor = ''
  }, [countryName, focusedCountry, setFocusedCountry])

  const handlePointerDown = useCallback((event) => {
    pointerDownRef.current = { x: event.clientX, y: event.clientY }
    draggingRef.current = false
  }, [])

  const handlePointerMove = useCallback((event) => {
    if (!pointerDownRef.current) return
    const dx = event.clientX - pointerDownRef.current.x
    const dy = event.clientY - pointerDownRef.current.y
    if (!draggingRef.current && Math.sqrt(dx * dx + dy * dy) > 4) {
      draggingRef.current = true
    }
  }, [])

  const handlePointerUp = useCallback((event) => {
    if (draggingRef.current) {
      pointerDownRef.current = null
      return
    }
    event.stopPropagation()
    pointerDownRef.current = null
    toggleCountry(countryName)
  }, [countryName, toggleCountry])

  const handlePointerCancel = useCallback(() => {
    pointerDownRef.current = null
    draggingRef.current = false
  }, [])

  if (!meshData) {
    return null
  }

  return (
    <group>
      <mesh
        geometry={meshData.fillGeometry}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        renderOrder={10}
      >
        <meshStandardMaterial
          color={fillColor}
          transparent
          opacity={fillOpacity}
          depthWrite={false}
          depthTest={false}
          side={THREE.DoubleSide}
          metalness={0.08}
          roughness={0.75}
          polygonOffset
          polygonOffsetFactor={-6}
          polygonOffsetUnits={-3}
        />
      </mesh>
      {meshData.outlineGeometries.map((geometry, index) => (
        <line
          key={`${countryName}-outline-${index}`}
          geometry={geometry}
          onPointerOver={handlePointerOver}
          onPointerOut={handlePointerOut}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          renderOrder={11}
        >
          <lineBasicMaterial color={outlineColor} transparent opacity={outlineOpacity} toneMapped={false} depthTest />
        </line>
      ))}
    </group>
  )
})

function GlobeScene() {
  const setGlobeReady = useUIStore((state) => state.setGlobeReady)
  const focusedRegion = useUIStore((state) => state.focusedRegion)
  const selectedRegions = useUIStore((state) => state.selectedRegions)
  const orbitRef = useRef()
  const focusTargetRef = useRef(DEFAULT_TARGET.clone())
  const cameraTargetRef = useRef(DEFAULT_CAMERA_POSITION.clone())
  const isInteractingRef = useRef(false)
  const lastFocusedRegionRef = useRef(null)
  const manualOverrideRef = useRef(0)
  const focusSuppressedRef = useRef(false)
  const focusResumeTimeoutRef = useRef(null)
  const lastZoomDistanceRef = useRef(DEFAULT_CAMERA_POSITION.length())
  const [geoDataLoaded, setGeoDataLoaded] = useState(false)

  // Lazy load GeoJSON data after component mounts
  useEffect(() => {
    loadGeoData().then(() => setGeoDataLoaded(true))
  }, [])

  // Build meshes lazily only after GeoJSON is loaded
  const regionMeshes = useMemo(() => {
    if (!geoDataLoaded || !COUNTRIES_BY_NAME) return new Map()
    return buildRegionMeshes(COUNTRIES_BY_NAME)
  }, [geoDataLoaded])

  const countryMeshes = useMemo(() => {
    if (!geoDataLoaded || !COUNTRY_FEATURES) return new Map()
    return buildCountryMeshes(COUNTRY_FEATURES)
  }, [geoDataLoaded])

  useEffect(() => {
    if (geoDataLoaded) {
      setGlobeReady(true)
    }
  }, [geoDataLoaded, setGlobeReady])

  useEffect(() => {
    const now = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
    const manualOverrideActive = now - manualOverrideRef.current < MANUAL_OVERRIDE_MS

    if (manualOverrideActive || focusSuppressedRef.current) {
      return
    }

    if (!focusedRegion || !selectedRegions.includes(focusedRegion)) {
      lastFocusedRegionRef.current = null
      return
    }
    if (isInteractingRef.current) {
      return
    }
    if (lastFocusedRegionRef.current === focusedRegion) {
      return
    }
    const regionDef = REGION_LOOKUP[focusedRegion]
    if (!regionDef) {
      return
    }
    const normal = latLongToVector(regionDef.center.lat, regionDef.center.lon, 1).normalize()
    focusTargetRef.current.copy(normal.clone().multiplyScalar(BASE_RADIUS * 0.12))
    cameraTargetRef.current.copy(normal.clone().multiplyScalar(3.2))
    lastFocusedRegionRef.current = focusedRegion
  }, [focusedRegion, selectedRegions])

  useEffect(() => {
    const controls = orbitRef.current
    if (!controls) return undefined

    controls.enableDamping = true
    controls.dampingFactor = 0.12
    controls.rotateSpeed = 0.42
    controls.zoomSpeed = 0.55
    controls.minDistance = BASE_RADIUS + 0.75
    controls.maxDistance = BASE_RADIUS + 3.2
    controls.enablePan = false
    controls.autoRotate = false
    controls.enableRotate = true
    controls.minAzimuthAngle = -Math.PI
    controls.maxAzimuthAngle = Math.PI

    controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: null
    }

    controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_PAN
    }

    const handleChange = () => {
      lastZoomDistanceRef.current = controls.getDistance()
    }

    const handleStart = () => {
      isInteractingRef.current = true
      controls.autoRotate = false
      manualOverrideRef.current = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
      focusSuppressedRef.current = true
      if (focusResumeTimeoutRef.current) {
        clearTimeout(focusResumeTimeoutRef.current)
        focusResumeTimeoutRef.current = null
      }
    }

    const handleEnd = () => {
      isInteractingRef.current = false
      manualOverrideRef.current = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
      focusTargetRef.current.copy(controls.target)
      cameraTargetRef.current.copy(controls.object.position)
      focusResumeTimeoutRef.current = setTimeout(() => {
        focusSuppressedRef.current = false
      }, FOCUS_RESUME_DELAY_MS)
    }

    controls.addEventListener('change', handleChange)
    controls.addEventListener('start', handleStart)
    controls.addEventListener('end', handleEnd)

    return () => {
      controls.removeEventListener('change', handleChange)
      controls.removeEventListener('start', handleStart)
      controls.removeEventListener('end', handleEnd)
      if (focusResumeTimeoutRef.current) {
        clearTimeout(focusResumeTimeoutRef.current)
      }
    }
  }, [])

  const AnimationLoop = useCallback(() => {
    useFrame((state, delta) => {
      const controls = orbitRef.current
      if (!controls) return
      const now = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
      const manualOverrideActive = now - manualOverrideRef.current < MANUAL_OVERRIDE_MS
      const currentDistance = controls.getDistance()
      const zoomChanged = Math.abs(currentDistance - lastZoomDistanceRef.current) > 0.003

      if (!isInteractingRef.current && !manualOverrideActive && !zoomChanged && !focusSuppressedRef.current) {
        controls.target.lerp(focusTargetRef.current, delta * 1.2)
        state.camera.position.lerp(cameraTargetRef.current, delta * 1.2)
      } else {
        focusTargetRef.current.lerp(controls.target, delta * 6)
        cameraTargetRef.current.lerp(state.camera.position, delta * 6)
      }
      lastZoomDistanceRef.current = currentDistance
      controls.update()
    })
    return null
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined
    }

    const readState = () => {
      const controls = orbitRef.current
      if (!controls || !controls.object) {
        return null
      }
      const { target, object } = controls
      const targetVector = target.clone()
      const cameraPosition = object.position.clone()
      const relative = cameraPosition.clone().sub(targetVector)
      const spherical = new THREE.Spherical().setFromVector3(relative)

      return {
        target: targetVector.toArray(),
        position: cameraPosition.toArray(),
        azimuthalAngle: typeof controls.getAzimuthalAngle === 'function' ? controls.getAzimuthalAngle() : null,
        polarAngle: typeof controls.getPolarAngle === 'function' ? controls.getPolarAngle() : null,
        radius: spherical.radius
      }
    }

    window.__BEACON_GLOBE__ = {
      getState: () => {
        const controls = orbitRef.current
        const base = readState()
        if (!base || !controls?.object) {
          return null
        }
        return {
          ...base,
          quaternion: controls.object.quaternion.toArray()
        }
      },
      getTarget: () => readState()?.target ?? null,
      getPosition: () => readState()?.position ?? null
    }

    return () => {
      if (window.__BEACON_GLOBE__) {
        delete window.__BEACON_GLOBE__
      }
    }
  }, [])

  if (!geoDataLoaded) {
    return null
  }

  return (
    <>
      <ambientLight intensity={0.55} />
      <directionalLight
        position={[6, 2, 4]}
        intensity={1.35}
        color="#ffffff"
      />
      <directionalLight position={[-6, -4, -2]} intensity={0.35} color="#5c6c7c" />

      <GlobeSurface />

      {REGION_DEFINITIONS.map((region) => {
        const meshData = regionMeshes.get(region.id)
        if (!meshData) {
          return null
        }
        return <RegionOverlay key={region.id} region={region} meshData={meshData} />
      })}
      {REGION_DEFINITIONS.filter((region) => selectedRegions.includes(region.id)).map((region) => (
        <group key={`countries-${region.id}`}>
          {region.countryNames.map((country) => (
            <CountryOverlay key={country} countryName={country} regionColor={region.color} countryMeshes={countryMeshes} />
          ))}
        </group>
      ))}

      <Stars radius={16} depth={80} count={400} factor={1.6} fade speed={0.2} />
      <OrbitControls
        ref={orbitRef}
        enablePan={false}
        enableZoom
        minPolarAngle={Math.PI / 2 - 0.9}
        maxPolarAngle={Math.PI / 2 + 0.9}
      />
      <AnimationLoop />
    </>
  )
}

export function GlobeCanvas() {
  return (
    <Canvas
      camera={{ position: [0, 0, 4.2], fov: 45 }}
      className="rounded-3xl"
    >
      <Suspense fallback={null}>
        <GlobeScene />
      </Suspense>
    </Canvas>
  )
}
