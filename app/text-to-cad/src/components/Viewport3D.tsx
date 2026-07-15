/**
 * 中央 3D 视图区组件
 * 支持程序化几何体(box/sphere/...)和 STL 文件加载(step 类型)
 * Three.js: 轨道控制、网格辅助、光照、线框切换
 * 3D 应力场着色: Web Worker 空间哈希映射 + 扇区表面网格剖视图
 */
import { useRef, useCallback, useState, useEffect, Suspense, useMemo } from 'react';
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
  Columns,
} from 'lucide-react';
import { jetColorRgb } from '../colormap';
import ColorbarOverlay from './ColorbarOverlay';
import { useStore } from '../store';
import type { SceneModel } from '../types';

/** STL 文件加载渲染 + Worker 驱动的 3D 应力场着色 */
function STLGeometry({ model, isSelected, onClick }: {
  model: SceneModel;
  isSelected: boolean;
  onClick: () => void;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireframeMode = useStore((s) => s.wireframeMode);
  const stressColoring = useStore((s) => s.stressColoring);
  const fea3dJob = useStore((s) => s.fea3dJob);
  const fea3dField = useStore((s) => s.fea3dField);
  const colorCache = useStore((s) => s.fea3dColorCache);
  const setFea3dRange = useStore((s) => s.setFea3dRange);
  const geometry = useLoader(STLLoader, model.stlUrl || '');

  // Center the STL geometry (record offset for stress mapping)
  const centerOffset = useRef<[number, number, number]>([0, 0, 0]);
  useEffect(() => {
    if (geometry) {
      geometry.computeBoundingBox();
      const bbox = geometry.boundingBox;
      if (bbox) {
        const cx = -(bbox.max.x + bbox.min.x) / 2;
        const cy = -(bbox.max.y + bbox.min.y) / 2;
        const cz = -(bbox.max.z + bbox.min.z) / 2;
        geometry.translate(cx, cy, cz);
        centerOffset.current = [-cx, -cy, -cz];  // undo offset for stress mapping
      }
    }
  }, [geometry]);

  // Worker 实例 (懒初始化)
  const workerRef = useRef<Worker | null>(null);
  useEffect(() => {
    return () => { workerRef.current?.terminate(); };
  }, []);

  // 3D 应力着色 (Worker)
  useEffect(() => {
    if (!geometry || !fea3dJob || !stressColoring) {
      if (geometry?.attributes.color) { geometry.deleteAttribute('color'); }
      return;
    }
    const pos = geometry.attributes.position;
    if (!pos || pos.count === 0) return;

    // 缓存命中 → 直接应用
    if (colorCache?.job === fea3dJob) {
      const cached = colorCache.colors.get(fea3dField);
      if (cached) {
        geometry.setAttribute('color', new THREE.BufferAttribute(cached, 3));
        geometry.attributes.color.needsUpdate = true;
        return;
      }
    }

    // Worker 未就绪 → 新建并 init
    const w = new Worker(new URL('../workers/stressWorker.ts', import.meta.url), { type: 'module' });
    workerRef.current = w;

    const vminInit = 0;
    const vmaxInit = 1200;

    w.onmessage = (e: MessageEvent) => {
      const msg = e.data;
      if (msg.type === 'ready') {
        // 发送顶点数据
        const n = pos.count;
        const arr = new Float32Array(n * 3);
        const ox = centerOffset.current[0];
        const oy = centerOffset.current[1];
        const oz = centerOffset.current[2];
        for (let i = 0; i < n; i++) {
          arr[i * 3] = pos.getX(i) + ox;  // 还原居中前的物理坐标
          arr[i * 3 + 1] = pos.getY(i) + oy;
          arr[i * 3 + 2] = pos.getZ(i) + oz;
        }
        w.postMessage({ type: 'colorize', field: fea3dField, positions: arr }, { transfer: [arr.buffer] });
      } else if (msg.type === 'colors') {
        const colors = msg.colors as Float32Array;
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        geometry.attributes.color.needsUpdate = true;
        // 更新缓存
        const store = useStore.getState();
        store.setFea3dColorCache(fea3dJob, fea3dField, colors);
        setFea3dRange({ vmin: vminInit, vmax: vmaxInit });
        w.terminate();
      } else if (msg.type === 'error') {
        console.error('[STLGeometry] Worker error:', msg.message);
        w.terminate();
        w.terminate();
      }
    };

    // 先 fetch bin → init worker
    fetch(`/api/fea3d/files/${fea3dJob}/stress_field_surface.bin`)
      .then(r => r.arrayBuffer())
      .then(buf => { w.postMessage({ type: 'init', data: buf, vmin: 0, vmax: 1200 }, { transfer: [buf] }); })
      .catch(err => {
        console.error('[STLGeometry] fetch bin failed:', err);
      });
  }, [geometry, fea3dJob, fea3dField, stressColoring, colorCache, setFea3dRange]);

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
        color={stressColoring && fea3dJob ? undefined : model.color}
        vertexColors={!!(stressColoring && fea3dJob)}
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

/** 扇区表面网格剖视图 — 视图B, 暴露内部三维应力场 */
function SectorStressMesh() {
  const fea3dJob = useStore((s) => s.fea3dJob);
  const fea3dField = useStore((s) => s.fea3dField);
  const fea3dViewMode = useStore((s) => s.fea3dViewMode);
  const stressColoring = useStore((s) => s.stressColoring);
  const [surface, setSurface] = useState<{
    positions: Float32Array; indices: Uint32Array; fields: Record<string, Float32Array>;
  } | null>(null);

  // 加载 sector_surface.json
  useEffect(() => {
    if (!fea3dJob) { setSurface(null); return; }
    fetch(`/api/fea3d/files/${fea3dJob}/sector_surface.json`)
      .then(r => r.json())
      .then(d => {
        setSurface({
          positions: new Float32Array(d.positions),
          indices: new Uint32Array(d.indices),
          fields: Object.fromEntries(
            Object.entries(d.fields as Record<string, number[]>).map(([k, v]) => [k, new Float32Array(v)])
          ),
        });
      })
      .catch(() => setSurface(null));
  }, [fea3dJob]);

  // 每顶点颜色 (主线程重算 — 表面节点仅 ~3k, <5ms)
  const colors = useMemo(() => {
    if (!surface || !stressColoring) return null;
    const arr = surface.fields[fea3dField];
    if (!arr) return null;
    const ranges = { s_vm: 1200, s_r: 1000, s_hoop: 1200, s_axial: 500, sf: 3 };
    const vmax = ranges[fea3dField] || 1000;
    const n = arr.length;
    const c = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const t = arr[i] / vmax;
      const [r, g, b] = jetColorRgb(t);
      c[i * 3] = r; c[i * 3 + 1] = g; c[i * 3 + 2] = b;
    }
    return c;
  }, [surface, fea3dField, stressColoring]);

  // Geometry — hook 必须在条件 return 之前无条件调用
  const geo = useMemo(() => {
    if (!surface) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(surface.positions, 3));
    g.setIndex(new THREE.BufferAttribute(surface.indices, 1));
    return g;
  }, [surface]);
  const colorAttr = useMemo(() => {
    if (!colors) return null;
    return new THREE.BufferAttribute(colors, 3);
  }, [colors]);

  if (fea3dViewMode !== 'sector' || !geo || !stressColoring) return null;

  return (
    <mesh scale={1.1} rotation={[0, 0, 0]}>
      <primitive object={geo} attach="geometry" />
      {colorAttr && (
        <primitive object={colorAttr} attach="attributes-color" />
      )}
      <meshStandardMaterial
        vertexColors={!!colors}
        side={THREE.DoubleSide}
        roughness={0.6}
        metalness={0.1}
      />
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
      <SectorStressMesh />

      <mesh onClick={() => setSelectedModel(null)} visible={false}>
        <planeGeometry args={[100, 100]} />
        <meshBasicMaterial />
      </mesh>

      <OrbitControls makeDefault enablePan enableZoom enableRotate
        minDistance={0.1} maxDistance={Infinity} target={[0, 0, 0]} />
    </>
  );
}

const FEA3D_FIELDS: { key: string; label: string }[] = [
  { key: 's_vm', label: 'Von Mises' },
  { key: 's_hoop', label: '环向' },
  { key: 's_r', label: '径向' },
  { key: 's_axial', label: '轴向' },
  { key: 'sf', label: '安全系数' },
];

function ViewportToolbar({ onReset, onScreenshot, stepUrl, stlUrl }: {
  onReset: () => void; onScreenshot: () => void;
  stepUrl?: string | null; stlUrl?: string | null;
}) {
  const {
    wireframeMode, setWireframeMode,
    stressColoring, setStressColoring,
    fea3dJob, setFea3dField, fea3dField,
    fea3dViewMode, setFea3dViewMode,
  } = useStore();
  const [showFieldMenu, setShowFieldMenu] = useState(false);

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
      {fea3dJob && (
        <>
          <button onClick={() => setStressColoring(!stressColoring)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${stressColoring ? 'bg-accent text-white' : 'hover:bg-bg-hover text-text-secondary'}`}>
              🌡️{stressColoring ? '应力开' : '应力关'}
          </button>
          {stressColoring && (
            <>
              {/* 分量选择 */}
              <div className="relative">
                <button onClick={() => setShowFieldMenu(!showFieldMenu)}
                  className="px-2.5 py-1.5 rounded-lg hover:bg-bg-hover text-text-secondary text-xs transition-colors">
                  {FEA3D_FIELDS.find(f => f.key === fea3dField)?.label || 'Von Mises'} ▾
                </button>
                {showFieldMenu && (
                  <div className="absolute top-full mt-1 left-0 bg-bg-secondary border border-border rounded-lg shadow-xl z-20 min-w-[100px]"
                       onMouseLeave={() => setShowFieldMenu(false)}>
                    {FEA3D_FIELDS.map(f => (
                      <button key={f.key} onClick={() => { setFea3dField(f.key as any); setShowFieldMenu(false); }}
                        className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-bg-hover transition-colors ${f.key === fea3dField ? 'text-accent' : 'text-text-secondary'}`}>
                        {f.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {/* 视图切换 */}
              <button onClick={() => setFea3dViewMode(fea3dViewMode === 'full' ? 'sector' : 'full')}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${fea3dViewMode === 'sector' ? 'bg-accent/80 text-white' : 'hover:bg-bg-hover text-text-secondary'}`}
                title={fea3dViewMode === 'full' ? '切换剖视图' : '切换全盘视图'}>
                <Columns className="w-3.5 h-3.5" />{fea3dViewMode === 'sector' ? '剖视' : '全盘'}
              </button>
            </>
          )}
        </>
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
  const stressColoring = useStore((s) => s.stressColoring);
  const fea3dRange = useStore((s) => s.fea3dRange);

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
      <ColorbarOverlay
        vmin={fea3dRange?.vmin ?? 0}
        vmax={fea3dRange?.vmax ?? 1000}
        unit="MPa"
        yieldVal={950}
        visible={stressColoring}
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
