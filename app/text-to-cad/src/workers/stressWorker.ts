/**
 * Web Worker — 3D 应力场最近邻映射.
 *
 * 协议 (主线程→Worker):
 *   {type:'init', data:ArrayBuffer, vmin:number, vmax:number}
 *   {type:'colorize', field:FieldName, positions:Float32Array} [transfer]
 *
 * 协议 (Worker→主线程):
 *   {type:'ready', nodeCount:number}
 *   {type:'colors', colors:Float32Array} [transfer]
 *   {type:'error', message:string}
 */

type FieldName = 's_vm' | 's_r' | 's_hoop' | 's_axial' | 'sf';

interface Point {
  x: number; y: number; z: number;
  s_vm: number; s_r: number; s_hoop: number; s_axial: number; sf: number;
}

// ---- 全局状态 (worker 存活期间复用) ----
let points: Point[] = [];
let grid: Map<number, number[]> = new Map(); // cellKey → pointIndices
let gridH = 4.0;                             // cell size mm
let vmin = 0, vmax = 1000;

// ---- 应力分量取用 ----
function fieldOf(p: Point, f: FieldName): number {
  switch (f) {
    case 's_vm':   return p.s_vm;
    case 's_r':    return p.s_r;
    case 's_hoop': return p.s_hoop;
    case 's_axial':return p.s_axial;
    case 'sf':     return p.sf;
  }
}

// ---- 对称映射: (x,y,z) → 扇区查询坐标 ----
// 扇区 θ∈[3°,9°], z∈[0,38]
const THETA_LOW = 3.0;
const SECTOR_DEG = 6.0;
const RAD2DEG = 180 / Math.PI;
const DEG2RAD = Math.PI / 180;

function mapToSector(x: number, y: number, z: number): [number, number, number] {
  const r = Math.hypot(x, y);
  if (r < 1e-6) return [0, 0, Math.abs(z)]; // 轴上点

  const theta = Math.atan2(y, x) * RAD2DEG;            // (-180, 180]
  let t = ((theta - THETA_LOW) % SECTOR_DEG + SECTOR_DEG) % SECTOR_DEG; // [0, 6)
  const thetaSector = THETA_LOW + t;
  const rad = thetaSector * DEG2RAD;
  return [r * Math.cos(rad), r * Math.sin(rad), Math.abs(z)];
}

// ---- 初始化: 解析二进制 → 建空间哈希网格 ----
function init(data: ArrayBuffer, newVmin: number, newVmax: number) {
  vmin = newVmin;
  vmax = newVmax;

  const header = new Uint32Array(data, 0, 4);
  const magic = header[0];
  if (magic !== 0x33444653 && magic !== 0x33534653) {
    self.postMessage({ type: 'error', message: 'Bad magic in stress field bin' });
    return;
  }
  const n = header[1];
  const f32 = new Float32Array(data, 16, n * 8);

  points = [];
  let minZ = Infinity, maxZ = -Infinity, minR = Infinity, maxR = -Infinity;
  for (let i = 0; i < n; i++) {
    const off = i * 8;
    const x = f32[off], y = f32[off + 1], z = f32[off + 2];
    const r = Math.hypot(x, y);
    if (r < minR) minR = r; if (r > maxR) maxR = r;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    points.push({
      x, y, z,
      s_vm: f32[off + 3], s_r: f32[off + 4], s_hoop: f32[off + 5],
      s_axial: f32[off + 6], sf: f32[off + 7],
    });
  }

  // 自适应 cell size: 均匀分布下 ~8 点/cell
  const cellSize = Math.max(3.0, Math.cbrt((maxR - minR) * (maxR - minR) * (maxZ - minZ) / n));
  gridH = cellSize;

  grid.clear();
  for (let i = 0; i < n; i++) {
    const p = points[i];
    const cx = Math.floor(p.x / gridH);
    const cy = Math.floor(p.y / gridH);
    const cz = Math.floor(p.z / gridH);
    // 30-bit key: 10 bits per axis (range ~±1023)
    const key = ((cx & 0x3FF) << 20) | ((cy & 0x3FF) << 10) | (cz & 0x3FF);
    let arr = grid.get(key);
    if (!arr) { arr = []; grid.set(key, arr); }
    arr.push(i);
  }

  self.postMessage({ type: 'ready', nodeCount: n });
}

// ---- 最近邻查询: 查询点 → 最近应力节点的分量值 ----
function lookup(qx: number, qy: number, qz: number, field: FieldName): number {
  const cx = Math.floor(qx / gridH);
  const cy = Math.floor(qy / gridH);
  const cz = Math.floor(qz / gridH);

  let bestD2 = Infinity, bestV = 0;

  // 第一环: 3×3×3 邻域桶
  for (let dcx = -1; dcx <= 1 && bestD2 > 1e-6; dcx++) {
    for (let dcy = -1; dcy <= 1 && bestD2 > 1e-6; dcy++) {
      for (let dcz = -1; dcz <= 1 && bestD2 > 1e-6; dcz++) {
        const key = (((cx + dcx) & 0x3FF) << 20) | (((cy + dcy) & 0x3FF) << 10) | ((cz + dcz) & 0x3FF);
        const arr = grid.get(key);
        if (!arr) continue;
        for (const idx of arr) {
          const p = points[idx];
          const dx = qx - p.x, dy = qy - p.y, dz = qz - p.z;
          const d2 = dx * dx + dy * dy + dz * dz;
          if (d2 < bestD2) {
            bestD2 = d2;
            bestV = fieldOf(p, field);
          }
        }
      }
    }
  }
  // 第一环 27 桶没找到足够好的 → 扩环 (最多 3 环)
  for (let ring = 2; ring <= 3 && bestD2 > gridH * gridH; ring++) {
    for (let dcx = -ring; dcx <= ring; dcx++) {
      for (let dcy = -ring; dcy <= ring; dcy++) {
        for (let dcz = -ring; dcz <= ring; dcz++) {
          // 跳过内环
          if (Math.abs(dcx) < ring && Math.abs(dcy) < ring && Math.abs(dcz) < ring) continue;
          const key = (((cx + dcx) & 0x3FF) << 20) | (((cy + dcy) & 0x3FF) << 10) | ((cz + dcz) & 0x3FF);
          const arr = grid.get(key);
          if (!arr) continue;
          for (const idx of arr) {
            const p = points[idx];
            const dx = qx - p.x, dy = qy - p.y, dz = qz - p.z;
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < bestD2) {
              bestD2 = d2;
              bestV = fieldOf(p, field);
            }
          }
        }
      }
    }
  }

  return bestD2 < gridH * gridH * 16 ? bestV : NaN;
}

// ---- 颜色映射: stress → RGB [0,1] (jet colormap, 与 src/colormap.ts 同步) ----
function stressToRgb(val: number): [number, number, number] {
  if (!isFinite(val)) return [0.3, 0.3, 0.3]; // NaN → gray
  const t = (val - vmin) / (vmax - vmin);
  const c = Math.max(0, Math.min(1, t));
  if (c < 0.125)    return [0, 0, 0.5 + 0.5 * (c / 0.125)];
  if (c < 0.375)    return [0, (c - 0.125) / 0.25, 1];
  if (c < 0.625)    return [(c - 0.375) / 0.25, 1, 1 - (c - 0.375) / 0.25];
  if (c < 0.875)    return [1, 1 - (c - 0.625) / 0.25, 0];
  return [1 - 0.5 * (c - 0.875) / 0.125, 0, 0];
}

// ---- 处理 colorize 请求 ----
function colorize(positions: Float32Array, field: FieldName) {
  const n = positions.length / 3;
  const colors = new Float32Array(n * 3);
  let nanCount = 0;

  for (let i = 0; i < n; i++) {
    const x = positions[i * 3];
    const y = positions[i * 3 + 1];
    const z = positions[i * 3 + 2];
    const [sx, sy, sz] = mapToSector(x, y, z);
    const val = lookup(sx, sy, sz, field);
    const [r, g, b] = stressToRgb(val);
    colors[i * 3] = r;
    colors[i * 3 + 1] = g;
    colors[i * 3 + 2] = b;
    if (!isFinite(val)) nanCount++;
  }

  if (nanCount / n > 0.01) {
    console.warn(`[stressWorker] ${nanCount}/${n} vertices (${(nanCount/n*100).toFixed(1)}%) returned NaN`);
  }

  self.postMessage({ type: 'colors', colors }, { transfer: [colors.buffer] });
}

// ---- 消息分发 ----
self.onmessage = (e: MessageEvent) => {
  const msg = e.data;
  try {
    switch (msg.type) {
      case 'init':
        init(msg.data, msg.vmin, msg.vmax);
        break;
      case 'colorize':
        colorize(msg.positions, msg.field);
        break;
      default:
        self.postMessage({ type: 'error', message: `Unknown message type: ${msg.type}` });
    }
  } catch (err: any) {
    self.postMessage({ type: 'error', message: err.message || String(err) });
  }
};
