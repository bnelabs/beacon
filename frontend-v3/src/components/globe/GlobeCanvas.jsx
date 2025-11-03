import { Canvas } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { Suspense } from 'react'
import Globe from './Globe'
import LoadingSpinner from '../ui/LoadingSpinner'

export default function GlobeCanvas({ onRegionClick, selectedRegion, autoRotate }) {
  return (
    <div className="relative w-full h-full bg-gradient-to-b from-bne-ink to-bne-indigo rounded-2xl overflow-hidden">
      <Canvas>
        <PerspectiveCamera makeDefault position={[0, 0, 6]} />

        <ambientLight intensity={0.5} />
        <directionalLight position={[10, 10, 5]} intensity={1} />
        <pointLight position={[-10, -10, -5]} intensity={0.5} color="#4a90e2" />

        <Suspense fallback={null}>
          <Globe
            onRegionClick={onRegionClick}
            selectedRegion={selectedRegion}
            autoRotate={autoRotate}
          />
        </Suspense>

        <OrbitControls
          enablePan={false}
          enableZoom={true}
          minDistance={4}
          maxDistance={10}
          rotateSpeed={0.5}
          zoomSpeed={0.8}
        />
      </Canvas>

      <div className="absolute top-4 right-4 flex flex-col gap-2">
        <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 text-xs">
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
