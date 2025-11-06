import { Canvas } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { Suspense } from 'react'
import Globe from './Globe'
import LoadingSpinner from '../ui/LoadingSpinner'

export default function GlobeCanvas({
  onRegionClick,
  selectedRegion,
  autoRotate,
  showNetwork,
  onConnectionClick
}) {
  return (
    <div className="relative w-full h-full rounded-2xl overflow-hidden bg-gradient-to-b from-[#0b1120] via-[#0f172a] to-[#111827]">
      <Canvas>
        <PerspectiveCamera makeDefault position={[0, 0, 6]} />

        <ambientLight intensity={0.6} />
        <directionalLight position={[8, 12, 10]} intensity={1.3} color="#bfdbfe" />
        <directionalLight position={[-6, -4, -8]} intensity={0.6} color="#1e293b" />

        <Suspense fallback={null}>
          <Globe
            onRegionClick={onRegionClick}
            selectedRegion={selectedRegion}
            autoRotate={autoRotate}
            showNetwork={showNetwork}
            onConnectionClick={onConnectionClick}
          />
        </Suspense>

        <OrbitControls
          enablePan={false}
          enableZoom
          minDistance={4}
          maxDistance={10}
          rotateSpeed={0.6}
          zoomSpeed={0.8}
        />
      </Canvas>

      <div className="pointer-events-none absolute inset-0 bg-gradient-radial from-transparent via-transparent to-black/40" />

      <div className="absolute top-4 right-4 flex flex-col gap-2">
        {/* Region Legend */}
        <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 text-xs">
          <p className="font-semibold text-bne-ink mb-2">Regions</p>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-bne-azure"></div>
            <span className="text-bne-steel">USA</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <div className="w-2 h-2 rounded-full bg-bne-emerald"></div>
            <span className="text-bne-steel">Europe</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <div className="w-2 h-2 rounded-full bg-bne-amber"></div>
            <span className="text-bne-steel">Asia</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <div className="w-2 h-2 rounded-full bg-bne-violet"></div>
            <span className="text-bne-steel">Oceania</span>
          </div>
        </div>

        {/* Network Risk Legend */}
        {showNetwork && (
          <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 text-xs">
            <p className="font-semibold text-bne-ink mb-2">Network Risk</p>
            <div className="flex items-center gap-2">
              <div className="w-3 h-0.5 rounded-full bg-[#10B981]"></div>
              <span className="text-bne-steel">Low</span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <div className="w-3 h-0.5 rounded-full bg-[#F59E0B]"></div>
              <span className="text-bne-steel">Medium</span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <div className="w-3 h-0.5 rounded-full bg-[#EF4444]"></div>
              <span className="text-bne-steel">High</span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <div className="w-3 h-0.5 rounded-full bg-[#DC2626]"></div>
              <span className="text-bne-steel">Critical</span>
            </div>
          </div>
        )}
      </div>

      {selectedRegion && (
        <div className="absolute bottom-4 left-4 right-4 bg-white/95 backdrop-blur-sm rounded-xl p-4 shadow-lg">
          <h3 className="font-semibold text-bne-ink mb-1">{selectedRegion.name}</h3>
          <p className="text-sm text-bne-steel">
            {selectedRegion.bankCount} banks
          </p>
        </div>
      )}
    </div>
  )
}
