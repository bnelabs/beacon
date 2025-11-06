import { useRef, useMemo, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { Line } from '@react-three/drei'
import { networkConnections, getRiskColor } from '../../data/network-connections'
import { regions } from '../../data/regions'

/**
 * Convert lat/lon to 3D vector on sphere
 */
function latLonToVector3(lat, lon, radius) {
  const phi = (90 - lat) * (Math.PI / 180)
  const theta = (lon + 180) * (Math.PI / 180)

  const x = -(radius * Math.sin(phi) * Math.cos(theta))
  const z = radius * Math.sin(phi) * Math.sin(theta)
  const y = radius * Math.cos(phi)

  return new THREE.Vector3(x, y, z)
}

/**
 * Generate arc curve between two points on sphere
 */
function createArcCurve(startPos, endPos, arcHeight = 0.5) {
  const mid = new THREE.Vector3()
    .addVectors(startPos, endPos)
    .multiplyScalar(0.5)

  // Add height to midpoint to create arc
  mid.normalize().multiplyScalar(mid.length() + arcHeight)

  // Create quadratic curve
  return new THREE.QuadraticBezierCurve3(startPos, mid, endPos)
}

/**
 * Single animated arc connection
 */
function NetworkArc({ connection, onHover, onLeave, onClick, isHovered }) {
  const lineRef = useRef()
  const particleRef = useRef()

  // Find source and target regions
  const sourceRegion = regions.find(r => r.id === connection.source)
  const targetRegion = regions.find(r => r.id === connection.target)

  // Calculate positions and curve
  const { curve, points, color, lineWidth } = useMemo(() => {
    if (!sourceRegion || !targetRegion) return { points: [], color: '#ffffff', lineWidth: 0.01 }

    const startPos = latLonToVector3(sourceRegion.lat, sourceRegion.lon, 2.05)
    const endPos = latLonToVector3(targetRegion.lat, targetRegion.lon, 2.05)

    // Arc height based on distance
    const distance = startPos.distanceTo(endPos)
    const arcHeight = Math.max(0.3, distance * 0.25)

    const curve = createArcCurve(startPos, endPos, arcHeight)
    const points = curve.getPoints(50)

    // Color based on risk
    const color = getRiskColor(connection.riskScore)

    // Line width based on exposure (normalized to 0.01-0.04 range)
    const maxExposure = 312000000000 // $312B (max in our data)
    const normalizedExposure = connection.exposure / maxExposure
    const lineWidth = 0.01 + normalizedExposure * 0.03

    return { curve, points, color, lineWidth }
  }, [sourceRegion, targetRegion, connection])

  // Animate particle along arc
  useFrame((state) => {
    if (particleRef.current && curve) {
      // Cycle time based on risk (higher risk = faster pulse)
      const cycleSpeed = 0.2 + connection.riskScore * 0.3
      const t = (state.clock.elapsedTime * cycleSpeed) % 1
      const point = curve.getPoint(t)
      particleRef.current.position.copy(point)

      // Pulse effect when hovered
      if (isHovered) {
        const scale = 1 + Math.sin(state.clock.elapsedTime * 5) * 0.3
        particleRef.current.scale.setScalar(scale)
      }
    }

    // Animate line opacity when hovered
    if (lineRef.current) {
      const targetOpacity = isHovered ? 1 : 0.6
      lineRef.current.material.opacity = THREE.MathUtils.lerp(
        lineRef.current.material.opacity,
        targetOpacity,
        0.1
      )
    }
  })

  if (points.length === 0) return null

  return (
    <group>
      {/* Main arc line */}
      <Line
        ref={lineRef}
        points={points}
        color={color}
        lineWidth={isHovered ? lineWidth * 1.5 : lineWidth}
        transparent
        opacity={0.6}
        onPointerOver={(e) => {
          e.stopPropagation()
          onHover(connection)
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={(e) => {
          e.stopPropagation()
          onLeave()
          document.body.style.cursor = 'default'
        }}
        onClick={(e) => {
          e.stopPropagation()
          onClick(connection)
        }}
      />

      {/* Animated particle */}
      <mesh ref={particleRef}>
        <sphereGeometry args={[0.02, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={isHovered ? 1 : 0.8}
          toneMapped={false}
        />
      </mesh>

      {/* Glow effect for hovered arc */}
      {isHovered && (
        <Line
          points={points}
          color={color}
          lineWidth={lineWidth * 3}
          transparent
          opacity={0.2}
        />
      )}
    </group>
  )
}

/**
 * All network arcs visualization
 */
export default function NetworkArcs({ visible = true, onConnectionClick }) {
  const [hoveredConnection, setHoveredConnection] = useState(null)

  if (!visible) return null

  return (
    <group>
      {networkConnections.map((connection) => (
        <NetworkArc
          key={connection.id}
          connection={connection}
          onHover={setHoveredConnection}
          onLeave={() => setHoveredConnection(null)}
          onClick={onConnectionClick}
          isHovered={hoveredConnection?.id === connection.id}
        />
      ))}
    </group>
  )
}
