import React, { useRef, useState, useEffect, useMemo, Suspense } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Stars } from '@react-three/drei';
import * as THREE from 'three';
import { feature } from 'topojson-client';
import { geoPath, geoOrthographic } from 'd3-geo';
import { Box, CircularProgress, Typography } from '@mui/material';
import { bneColors, globeTheme } from '../../theme/bneTheme';
import { REGIONS, Region } from '../../data/worldRegions';

interface GlobeVisualizationProps {
  selectedRegion: string | null;
  onRegionSelect: (regionId: string | null) => void;
  hoveredRegion: string | null;
  onRegionHover: (regionId: string | null) => void;
}

interface CountryGeometry {
  type: string;
  id: string;
  properties: {
    name: string;
  };
  geometry: any;
}

/**
 * Globe mesh with Earth texture and atmosphere
 */
function GlobeMesh({
  selectedRegion,
  hoveredRegion,
  countriesData,
  onCountryClick,
  onCountryHover,
}: {
  selectedRegion: string | null;
  hoveredRegion: string | null;
  countriesData: CountryGeometry[];
  onCountryClick: (countryId: string) => void;
  onCountryHover: (countryId: string | null) => void;
}) {
  const globeRef = useRef<THREE.Group>(null);
  const [rotation, setRotation] = useState(0);

  // Auto-rotate when no region selected
  useFrame((state, delta) => {
    if (globeRef.current && !selectedRegion) {
      globeRef.current.rotation.y += delta * 0.05;
      setRotation(globeRef.current.rotation.y);
    }
  });

  // Create country meshes from GeoJSON
  const countryMeshes = useMemo(() => {
    if (!countriesData || countriesData.length === 0) return null;

    const projection = geoOrthographic()
      .scale(100)
      .translate([0, 0])
      .precision(0.1);

    const path = geoPath(projection);

    const meshes: JSX.Element[] = [];

    countriesData.forEach((country) => {
      const pathData = path(country as any);
      if (!pathData) return;

      // Determine region for this country
      const countryCode = country.id;
      const regionId = Object.keys(REGIONS).find(rid =>
        REGIONS[rid].countries.includes(countryCode)
      );

      if (!regionId) return;

      const region = REGIONS[regionId];
      const isSelected = selectedRegion === regionId;
      const isHovered = hoveredRegion === regionId;

      // Parse SVG path and create shape
      const shape = new THREE.Shape();
      const commands = pathData.match(/[A-Z][^A-Z]*/g) || [];

      commands.forEach((cmd) => {
        const type = cmd[0];
        const coords = cmd
          .slice(1)
          .trim()
          .split(/[\s,]+/)
          .map(Number);

        switch (type) {
          case 'M':
            shape.moveTo(coords[0] / 100, -coords[1] / 100);
            break;
          case 'L':
            shape.lineTo(coords[0] / 100, -coords[1] / 100);
            break;
          case 'Z':
            shape.closePath();
            break;
        }
      });

      const geometry = new THREE.ShapeGeometry(shape);

      // Calculate color
      let color = isSelected
        ? globeTheme.selected.fill
        : isHovered
        ? globeTheme.hover.fill
        : region.color;

      meshes.push(
        <mesh
          key={country.id}
          geometry={geometry}
          position={[0, 0, 1.01]}
          onClick={(e) => {
            e.stopPropagation();
            onCountryClick(regionId);
          }}
          onPointerOver={(e) => {
            e.stopPropagation();
            onCountryHover(regionId);
            document.body.style.cursor = 'pointer';
          }}
          onPointerOut={() => {
            onCountryHover(null);
            document.body.style.cursor = 'default';
          }}
        >
          <meshStandardMaterial
            color={color}
            emissive={isSelected || isHovered ? color : undefined}
            emissiveIntensity={isSelected ? 0.5 : isHovered ? 0.3 : 0}
            transparent
            opacity={isSelected ? 1 : 0.9}
          />
        </mesh>
      );
    });

    return meshes;
  }, [countriesData, selectedRegion, hoveredRegion, onCountryClick, onCountryHover]);

  return (
    <group ref={globeRef}>
      {/* Base globe sphere */}
      <mesh>
        <sphereGeometry args={[1, 64, 64]} />
        <meshPhongMaterial
          color={globeTheme.globe.base}
          emissive={bneColors.primary[800]}
          emissiveIntensity={0.1}
          shininess={10}
        />
      </mesh>

      {/* Atmosphere glow */}
      <mesh scale={1.015}>
        <sphereGeometry args={[1, 64, 64]} />
        <meshBasicMaterial
          color={globeTheme.globe.atmosphere}
          transparent
          opacity={0.1}
          side={THREE.BackSide}
        />
      </mesh>

      {/* Country meshes */}
      {countryMeshes}
    </group>
  );
}

/**
 * Animated camera controller
 */
function CameraController({
  selectedRegion,
  targetPosition,
}: {
  selectedRegion: string | null;
  targetPosition: [number, number, number];
}) {
  const { camera } = useThree();
  const targetRef = useRef(new THREE.Vector3(...targetPosition));

  useEffect(() => {
    targetRef.current.set(...targetPosition);
  }, [targetPosition]);

  useFrame((state, delta) => {
    // Smooth camera movement
    camera.position.lerp(targetRef.current, delta * 2);
    camera.lookAt(0, 0, 0);
  });

  return null;
}

/**
 * Main Globe Visualization Component
 */
export default function GlobeVisualization({
  selectedRegion,
  onRegionSelect,
  hoveredRegion,
  onRegionHover,
}: GlobeVisualizationProps) {
  const [countriesData, setCountriesData] = useState<CountryGeometry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load world topology data
  useEffect(() => {
    fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json')
      .then((response) => response.json())
      .then((topology) => {
        const countries = feature(
          topology,
          topology.objects.countries
        ) as any;
        setCountriesData(countries.features);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load world data:', err);
        setError('Failed to load world map data');
        setLoading(false);
      });
  }, []);

  // Calculate camera position based on selected region
  const cameraPosition: [number, number, number] = useMemo(() => {
    if (!selectedRegion || selectedRegion === 'global') {
      return [0, 0, 3];
    }

    const region = REGIONS[selectedRegion];
    if (!region) return [0, 0, 3];

    const [lon, lat] = region.center;
    const zoom = region.zoomLevel;

    // Convert lon/lat to 3D position
    const phi = (90 - lat) * (Math.PI / 180);
    const theta = (lon + 180) * (Math.PI / 180);

    const distance = 3 / zoom;

    return [
      distance * Math.sin(phi) * Math.cos(theta),
      distance * Math.cos(phi),
      distance * Math.sin(phi) * Math.sin(theta),
    ];
  }, [selectedRegion]);

  if (loading) {
    return (
      <Box
        sx={{
          width: '100%',
          height: '600px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: globeTheme.background,
          borderRadius: 2,
        }}
      >
        <CircularProgress size={60} sx={{ color: bneColors.primary[500] }} />
        <Typography sx={{ mt: 2, color: bneColors.neutral[400] }}>
          Loading Globe...
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box
        sx={{
          width: '100%',
          height: '600px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: globeTheme.background,
          borderRadius: 2,
        }}
      >
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        width: '100%',
        height: '600px',
        bgcolor: globeTheme.background,
        borderRadius: 2,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <Canvas>
        <PerspectiveCamera makeDefault position={cameraPosition} fov={45} />

        {/* Lighting */}
        <ambientLight intensity={0.3} />
        <pointLight position={[10, 10, 10]} intensity={1} />
        <pointLight position={[-10, -10, -10]} intensity={0.5} />

        {/* Stars background */}
        <Stars
          radius={100}
          depth={50}
          count={5000}
          factor={4}
          saturation={0}
          fade
          speed={0.5}
        />

        {/* Globe */}
        <Suspense fallback={null}>
          <GlobeMesh
            selectedRegion={selectedRegion}
            hoveredRegion={hoveredRegion}
            countriesData={countriesData}
            onCountryClick={onRegionSelect}
            onCountryHover={onRegionHover}
          />
        </Suspense>

        {/* Camera controller */}
        <CameraController
          selectedRegion={selectedRegion}
          targetPosition={cameraPosition}
        />

        {/* Orbit controls */}
        <OrbitControls
          enableZoom={true}
          enablePan={false}
          minDistance={2}
          maxDistance={5}
          rotateSpeed={0.5}
        />
      </Canvas>

      {/* Legend */}
      {!selectedRegion && (
        <Box
          sx={{
            position: 'absolute',
            bottom: 20,
            left: 20,
            bgcolor: 'rgba(15, 23, 42, 0.8)',
            backdropFilter: 'blur(10px)',
            borderRadius: 2,
            p: 2,
            border: `1px solid ${bneColors.neutral[700]}`,
          }}
        >
          <Typography
            variant="caption"
            sx={{ color: bneColors.neutral[300], display: 'block', mb: 1 }}
          >
            Click a region to explore
          </Typography>
          {Object.values(REGIONS)
            .filter((r) => r.id !== 'global')
            .map((region) => (
              <Box
                key={region.id}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  mb: 0.5,
                  cursor: 'pointer',
                  '&:hover': {
                    opacity: 0.8,
                  },
                }}
                onClick={() => onRegionSelect(region.id)}
              >
                <Box
                  sx={{
                    width: 16,
                    height: 16,
                    bgcolor: region.color,
                    borderRadius: 0.5,
                  }}
                />
                <Typography variant="caption" sx={{ color: bneColors.neutral[200] }}>
                  {region.displayName}
                </Typography>
              </Box>
            ))}
        </Box>
      )}
    </Box>
  );
}
