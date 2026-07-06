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

/** STL 文件加载渲染 */
function STLGeometry({ model, isSelected, onClick }: {
  model: SceneModel;
  isSelected: boolean;
  onClick: () => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireframeMode = useStore((s) => s.wireframeMode);

  const geometry = useLoader(STLLoader, model.stlUrl || '');

  // Center the STL geometry
  useEffect(() => {
    if (geometry) {
      geometry.computeBoundingBox();
      const bbox = geometry.boundingBox;
      if (bbox) {
        const cx = -(bbox.max.x + bbox.min.x) / 2;
        const cy = -(bbox.max.y + bbox.min.y) / 2;
        const cz = -(bbox.max.z + bbox.min.z) / 2;
        geometry.translate(cx, cy, cz);
      }
    }
  }, [geometry]);

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
      position={model.position}
      rotation={model.rotation}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      castShadow
      receiveShadow
    >
      <primitive object={geometry} attach="geometry" />
      <meshStandardMaterial
        color={model.color}
        wireframe={wireframeMode}
        roughness={0.4}
        metalness={0.3}
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
  const { wireframeMode, setWireframeMode } = useStore();
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
