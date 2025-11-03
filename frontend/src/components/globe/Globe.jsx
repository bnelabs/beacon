import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Sphere } from '@react-three/drei'
import * as THREE from 'three'
import { regions } from '../../data/regions'

function latLonToVector3(lat, lon, radius) {
  const phi = (90 - lat) * (Math.PI / 180)
  const theta = (lon + 180) * (Math.PI / 180)

  const x = -(radius * Math.sin(phi) * Math.cos(theta))
  const z = radius * Math.sin(phi) * Math.sin(theta)
  const y = radius * Math.cos(phi)

  return new THREE.Vector3(x, y, z)
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

export default function Globe({ onRegionClick, selectedRegion, autoRotate = true }) {
  const globeRef = useRef()

  useFrame(() => {
    if (globeRef.current && autoRotate) {
      globeRef.current.rotation.y += 0.001
    }
  })

  return (
    <group ref={globeRef}>
      <Sphere args={[2, 64, 64]}>
        <meshStandardMaterial
          color="#1e3a5f"
          emissive="#0a1929"
          emissiveIntensity={0.2}
          roughness={0.8}
          metalness={0.2}
        />
      </Sphere>

      <Sphere args={[2.005, 64, 64]}>
        <meshBasicMaterial
          color="#4a90e2"
          transparent
          opacity={0.1}
          side={THREE.DoubleSide}
        />
      </Sphere>

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
