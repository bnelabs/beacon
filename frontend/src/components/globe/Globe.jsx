import { useRef, useMemo, useEffect } from 'react'
import { extend, useFrame } from '@react-three/fiber'
import { Sphere, shaderMaterial } from '@react-three/drei'
import * as THREE from 'three'
import { regions } from '../../data/regions'
import coastlineData from '../../data/world-coastlines.json'
import NetworkArcs from './NetworkArcs'

function latLonToVector3(lat, lon, radius) {
  const phi = (90 - lat) * (Math.PI / 180)
  const theta = (lon + 180) * (Math.PI / 180)

  const x = -(radius * Math.sin(phi) * Math.cos(theta))
  const z = radius * Math.sin(phi) * Math.sin(theta)
  const y = radius * Math.cos(phi)

  return new THREE.Vector3(x, y, z)
}

const GlobeGradientMaterial = shaderMaterial(
  {
    colorA: new THREE.Color('#0f172a'),
    colorB: new THREE.Color('#2563eb')
  },
  /* glsl */`
    varying vec3 vPosition;
    void main() {
      vPosition = position;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  /* glsl */`
    uniform vec3 colorA;
    uniform vec3 colorB;
    varying vec3 vPosition;
    void main() {
      vec3 n = normalize(vPosition);
      float gradient = clamp(n.y * 0.5 + 0.5, 0.0, 1.0);
      vec3 color = mix(colorB, colorA, gradient);
      gl_FragColor = vec4(color, 1.0);
    }
  `
)

extend({ GlobeGradientMaterial })

function Graticule({ radius = 2.02, latStep = 15, lonStep = 15, color = '#60a5fa', opacity = 0.12 }) {
  const geometry = useMemo(() => {
    const positions = []
    const pushSegment = (a, b) => {
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z)
    }

    for (let lat = -75; lat <= 75; lat += latStep) {
      for (let lon = 0; lon < 360; lon += 5) {
        const start = latLonToVector3(lat, lon, radius)
        const end = latLonToVector3(lat, lon + 5, radius)
        pushSegment(start, end)
      }
    }

    for (let lon = 0; lon < 360; lon += lonStep) {
      for (let lat = -80; lat < 80; lat += 5) {
        const start = latLonToVector3(lat, lon, radius)
        const end = latLonToVector3(lat + 5, lon, radius)
        pushSegment(start, end)
      }
    }

    const buffer = new THREE.BufferGeometry()
    buffer.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    return buffer
  }, [latStep, lonStep, radius])

  useEffect(() => () => geometry.dispose(), [geometry])

  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color={color} transparent opacity={opacity} />
    </lineSegments>
  )
}

function Atmosphere({ radius = 2.25 }) {
  return (
    <Sphere args={[radius, 64, 64]}>
      <meshBasicMaterial
        color="#3b82f6"
        transparent
        opacity={0.08}
        side={THREE.BackSide}
        blending={THREE.AdditiveBlending}
      />
    </Sphere>
  )
}

function Coastlines({ radius = 2.01 }) {
  const geometries = useMemo(() => {
    const features = coastlineData.features || []
    return features.map((feature) => {
      const geometry = new THREE.BufferGeometry()
      const vertices = []
      feature.rings.forEach((ring) => {
        const points = ring.map(([lat, lon]) => latLonToVector3(lat, lon, radius))
        for (let i = 0; i < points.length - 1; i++) {
          const a = points[i]
          const b = points[i + 1]
          vertices.push(a.x, a.y, a.z, b.x, b.y, b.z)
        }
      })
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
      return geometry
    })
  }, [radius])

  useEffect(() => () => geometries.forEach((geometry) => geometry.dispose()), [geometries])

  return (
    <group>
      {geometries.map((geometry, index) => (
        <lineSegments key={index} geometry={geometry}>
          <lineBasicMaterial color="#60a5fa" transparent opacity={0.35} linewidth={0.5} />
        </lineSegments>
      ))}
    </group>
  )
}

function RegionMarker({ region, onClick, isSelected }) {
  const meshRef = useRef()
  const position = useMemo(
    () => latLonToVector3(region.lat, region.lon, 2.01),
    [region.lat, region.lon]
  )

  useFrame((state) => {
    if (meshRef.current && isSelected) {
      meshRef.current.scale.setScalar(
        0.8 + Math.sin(state.clock.elapsedTime * 3) * 0.2
      )
    }
  })

  return (
    <mesh
      ref={meshRef}
      position={position}
      onClick={(e) => {
        e.stopPropagation()
        onClick(region)
      }}
      scale={isSelected ? 1 : 0.6}
    >
      <sphereGeometry args={[0.05, 16, 16]} />
      <meshStandardMaterial
        color={region.color}
        emissive={region.color}
        emissiveIntensity={isSelected ? 0.8 : 0.3}
        toneMapped={false}
      />
    </mesh>
  )
}

export default function Globe({
  onRegionClick,
  selectedRegion,
  autoRotate = true,
  showNetwork = false,
  onConnectionClick
}) {
  const globeRef = useRef()

  useFrame(() => {
    if (globeRef.current && autoRotate) {
      globeRef.current.rotation.y += 0.001
    }
  })

  return (
    <group ref={globeRef}>
      <Sphere args={[2, 128, 128]}>
        <globeGradientMaterial colorA="#0f172a" colorB="#2563eb" attach="material" />
      </Sphere>

      <Graticule radius={2.025} opacity={0.1} />
      <Coastlines radius={2.012} />
      <Atmosphere radius={2.2} />

      {/* Network connections visualization */}
      <NetworkArcs visible={showNetwork} onConnectionClick={onConnectionClick} />

      {regions.map((region) => (
        <RegionMarker
          key={region.id}
          region={region}
          onClick={onRegionClick}
          isSelected={selectedRegion?.id === region.id}
        />
      ))}
    </group>
  )
}
