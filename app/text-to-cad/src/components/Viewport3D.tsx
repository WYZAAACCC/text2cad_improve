/**
 * 中央 3D 视图区组件
 * 支持程序化几何体(box/sphere/...)和 STL 文件加载(step 类型)
 * Three.js: 轨道控制、网格辅助、光照、线框切换
 */
import { useRef, useCallback, useState, useEffect, Suspense } from 'react';
import { Canvas, useFrame, useLoader } from '@react-three/fiber';
import {
  OrbitControls,
  Grid,
  PerspectiveCamera,
} from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import {
  RotateCcw,
  Box,
  Camera,
  Download,
} from 'lucide-react';
import { useStore } from '../store';
import type { SceneModel } from '../types';

/** Jet colormap: value in [vmin,vmax] → RGB */
function jetColor(t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.125) return [0, 0, Math.round(128 + 127 * (t / 0.125))];
  if (t < 0.375) return [0, Math.round(255 * ((t - 0.125) / 0.25)), 255];
  if (t < 0.625) return [Math.round(255 * ((t - 0.375) / 0.25)), 255, Math.round(255 * (1 - (t - 0.375) / 0.25))];
  if (t < 0.875) return [255, Math.round(255 * (1 - (t - 0.625) / 0.25)), 0];
  return [Math.round(128 + 127 * (1 - (t - 0.875) / 0.125)), 0, 0];
}

/** Find nearest stress value for (r, z) using simple linear scan */
function lookupStress(r: number, z: number, points: {r_mm:number;z_mm:number;seqv_mpa:number}[]): number {
  let bestD = Infinity, bestV = 0;
  for (const p of points) {
    const dr = r - p.r_mm, dz = z - p.z_mm;
    const d2 = dr*dr + dz*dz;
    if (d2 < bestD) { bestD = d2; bestV = p.seqv_mpa; }
    if (d2 < 0.01) break;
  }
  return bestV;
}

/** STL 文件加载渲染 + 3D 应力场着色 */
function STLGeometry({ model, isSelected, onClick }: {
  model: SceneModel;
  isSelected: boolean;
  onClick: () => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireframeMode = useStore((s) => s.wireframeMode);
  const stressField = useStore((s) => s.feaResult?.stress_field);
  const stressColoring = useStore((s) => s.stressColoring);

  const geometry = useLoader(STLLoader, model.stlUrl || '');

  // Compute centering offset for visual placement WITHOUT modifying geometry data.
  // Geometry vertices stay in original CAD coordinates so that stress-field
  // lookups (r = √(x²+y²), z) match the ANSYS axisymmetric coordinate system.
  // Uses state (not ref) so the mesh re-renders at the correct position.
  const [centerOffset, setCenterOffset] = useState<[number, number, number]>([0, 0, 0]);
  useEffect(() => {
    if (geometry) {
      geometry.computeBoundingBox();
      const bbox = geometry.boundingBox;
      if (bbox) {
        setCenterOffset([
          -(bbox.max.x + bbox.min.x) / 2,
          -(bbox.max.y + bbox.min.y) / 2,
          -(bbox.max.z + bbox.min.z) / 2,
        ]);
      }
    }
  }, [geometry]);

  // Apply stress coloring
  useEffect(() => {
    if (!geometry || !stressField || stressField.length === 0 || !stressColoring) {
      // Remove vertex colors if stress coloring is off
      if (geometry && geometry.attributes.color) {
        geometry.deleteAttribute('color');
      }
      return;
    }
    const pos = geometry.attributes.position;
    if (!pos) return;
    const n = pos.count;
    // Find stress range
    let vmin = Infinity, vmax = -Infinity;
    for (const p of stressField) {
      if (p.seqv_mpa < vmin) vmin = p.seqv_mpa;
      if (p.seqv_mpa > vmax) vmax = p.seqv_mpa;
    }
    if (!isFinite(vmin)) { vmin = 0; vmax = 1000; }
    const colors = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const r = Math.sqrt(x*x + y*y);
      const seqv = lookupStress(r, z, stressField);
      const t = (seqv - vmin) / (vmax - vmin);
      const [cr, cg, cb] = jetColor(t);
      colors[i*3] = cr / 255;
      colors[i*3+1] = cg / 255;
      colors[i*3+2] = cb / 255;
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.attributes.color.needsUpdate = true;
  }, [geometry, stressField, stressColoring]);

  useFrame((state) => {
    if (meshRef.current && isSelected) {
      const s = 1 + Math.sin(state.clock.elapsedTime * 3) * 0.005;
      meshRef.current.scale.setScalar(s);
    }
  });

  if (!model.visible) return null;

  return (
    <mesh
      ref={meshRef}
      position={[
        model.position[0] + centerOffset[0],
        model.position[1] + centerOffset[1],
        model.position[2] + centerOffset[2],
      ]}
      rotation={model.rotation}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      castShadow
      receiveShadow
    >
      <primitive object={geometry} attach="geometry" />
      <meshStandardMaterial
        color={stressColoring && stressField?.length ? undefined : model.color}
        vertexColors={!!(stressColoring && stressField?.length)}
        wireframe={wireframeMode}
        roughness={0.5}
        metalness={0.2}
        flatShading={false}
      />
      {isSelected && !wireframeMode && (
        <mesh>
          <primitive object={geometry} attach="geometry" />
          <meshBasicMaterial color="#ffffff" wireframe transparent opacity={0.3} />
        </mesh>
      )}
    </mesh>
  );
}

/** 程序化几何体渲染 */
function PrimitiveGeometry({ model, isSelected, onClick }: {
  model: SceneModel;
  isSelected: boolean;
  onClick: () => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireframeMode = useStore((s) => s.wireframeMode);

  useFrame((state) => {
    if (meshRef.current && isSelected) {
      const s = 1 + Math.sin(state.clock.elapsedTime * 3) * 0.005;
      meshRef.current.scale.setScalar(s);
    }
  });

  const geom = () => {
    const p = model.parameters as Record<string, number>;
    switch (model.type) {
      case 'box': return <boxGeometry args={[p.width || 1, p.height || 1, p.depth || 1]} />;
      case 'sphere': return <sphereGeometry args={[p.radius || 1, 32, 32]} />;
      case 'cylinder': return <cylinderGeometry args={[p.radius || 1, p.radius || 1, p.length || 2, 32]} />;
      case 'cone': return <coneGeometry args={[p.radius || 1, p.length || 2, 32]} />;
      case 'torus': return <torusGeometry args={[p.radius || 2, p.tube || 0.5, 16, 100]} />;
      default: return <boxGeometry args={[1, 1, 1]} />;
    }
  };

  if (!model.visible) return null;

  return (
    <mesh
      ref={meshRef}
      position={model.position}
      rotation={model.rotation}
      scale={model.scale}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      castShadow
      receiveShadow
    >
      {geom()}
      <meshStandardMaterial
        color={model.color}
        wireframe={wireframeMode}
        transparent={!wireframeMode}
        opacity={0.9}
        roughness={0.3}
        metalness={0.2}
      />
      {isSelected && !wireframeMode && (
        <mesh>
          {geom()}
          <meshBasicMaterial color="#ffffff" wireframe transparent opacity={0.3} />
        </mesh>
      )}
    </mesh>
  );
}

/** 单个模型 — 根据类型选择渲染方式 */
function ModelGeometry({ model, isSelected, onClick }: {
  model: SceneModel;
  isSelected: boolean;
  onClick: () => void;
}) {
  // step type: only render if STL URL is available
  if (model.type === 'step') {
    if (model.stlUrl) {
      return (
        <Suspense fallback={null}>
          <STLGeometry model={model} isSelected={isSelected} onClick={onClick} />
        </Suspense>
      );
    }
    return null; // no STL = nothing to render
  }
  return <PrimitiveGeometry model={model} isSelected={isSelected} onClick={onClick} />;
}

/** 场景内容 */
function SceneContent() {
  const { sceneModels, selectedModelId, setSelectedModel } = useStore();

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 10, 5]} intensity={1} castShadow
        shadow-mapSize-width={2048} shadow-mapSize-height={2048} />
      <directionalLight position={[-5, -5, -5]} intensity={0.3} />

      <Grid position={[0, -2, 0]} args={[20, 20]} cellSize={1} cellThickness={0.5}
        cellColor="#2e2e36" sectionSize={5} sectionThickness={1} sectionColor="#3a3a44"
        fadeDistance={30} fadeStrength={1} infiniteGrid />

      {sceneModels.map((model) => (
        <ModelGeometry key={model.id} model={model}
          isSelected={model.id === selectedModelId}
          onClick={() => setSelectedModel(model.id)} />
      ))}

      <mesh onClick={() => setSelectedModel(null)} visible={false}>
        <planeGeometry args={[100, 100]} />
        <meshBasicMaterial />
      </mesh>

      <OrbitControls makeDefault enablePan enableZoom enableRotate
        minDistance={0.1} maxDistance={Infinity} target={[0, 0, 0]} />
    </>
  );
}

function ViewportToolbar({ onReset, onScreenshot, stepUrl, stlUrl }: {
  onReset: () => void; onScreenshot: () => void;
  stepUrl?: string | null; stlUrl?: string | null;
}) {
  const { wireframeMode, setWireframeMode, stressColoring, setStressColoring, feaResult } = useStore();
  const hasStress = !!(feaResult?.stress_field?.length);
  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1 bg-bg-secondary/90 backdrop-blur-sm border border-border rounded-xl px-2 py-1.5 shadow-lg">
      <button onClick={onReset} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-bg-hover text-text-secondary text-xs transition-colors" title="重置视图">
        <RotateCcw className="w-3.5 h-3.5" />重置
      </button>
      <div className="w-px h-4 bg-border mx-1" />
      <button onClick={() => setWireframeMode(!wireframeMode)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${wireframeMode ? 'bg-accent text-white' : 'hover:bg-bg-hover text-text-secondary'}`} title="切换线框模式">
        <Box className="w-3.5 h-3.5" />{wireframeMode ? '线框' : '材质'}
      </button>
      {hasStress && (
        <button onClick={() => setStressColoring(!stressColoring)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${stressColoring ? 'bg-accent text-white' : 'hover:bg-bg-hover text-text-secondary'}`} title="3D应力场着色">
          🌡️{stressColoring ? '应力开' : '应力关'}
        </button>
      )}
      <div className="w-px h-4 bg-border mx-1" />
      <button onClick={onScreenshot} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-bg-hover text-text-secondary text-xs transition-colors" title="导出截图">
        <Camera className="w-3.5 h-3.5" />截图
      </button>
      {stepUrl && (
        <a href={stepUrl} download
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-accent/10 hover:bg-accent/20 text-accent text-xs transition-colors" title="下载 STEP 文件">
          <Download className="w-3.5 h-3.5" />STEP
        </a>
      )}
      {stlUrl && (
        <a href={stlUrl} download
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-accent/10 hover:bg-accent/20 text-accent text-xs transition-colors" title="下载 STL 文件">
          <Download className="w-3.5 h-3.5" />STL
        </a>
      )}
    </div>
  );
}

export default function Viewport3D() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [cameraKey, setCameraKey] = useState(0);
  const lastResult = useStore((s) => s.lastGenerationResult);

  const handleReset = useCallback(() => setCameraKey((prev) => prev + 1), []);

  const handleScreenshot = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const link = document.createElement('a');
    link.download = `cad-view-${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, []);

  return (
    <div className="relative w-full h-full bg-bg-primary">
      <ViewportToolbar
        onReset={handleReset}
        onScreenshot={handleScreenshot}
        stepUrl={lastResult?.stepFileUrl}
        stlUrl={lastResult?.stlFileUrl}
      />
      <Canvas key={cameraKey} ref={canvasRef} shadows
        camera={{ position: [5, 5, 5], fov: 50 }}
        gl={{ antialias: true, preserveDrawingBuffer: true, alpha: false }}
        style={{ background: '#0f0f12' }}>
        <PerspectiveCamera makeDefault position={[5, 5, 5]} fov={50} />
        <SceneContent />
      </Canvas>
      <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between pointer-events-none">
        <div className="bg-bg-secondary/80 backdrop-blur-sm rounded-lg px-3 py-1.5 text-xs text-text-muted">
          鼠标左键旋转 · 右键平移 · 滚轮缩放
        </div>
      </div>
    </div>
  );
}
