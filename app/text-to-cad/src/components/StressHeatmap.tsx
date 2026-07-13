/**
 * StressHeatmap — Canvas 2D heatmap of axisymmetric disc stress field.
 * X axis = radial (R, mm), Y axis = axial (Z, mm), color = Von Mises (MPa).
 */
import { useRef, useEffect } from 'react';
import type { StressPoint } from '../types';

interface Props {
  stressField: StressPoint[];
  /** disc cross-section polygon points [{r_mm, z_mm}] for overlay outline */
  discOutline?: { r_mm: number; z_mm: number }[];
  yieldMpa?: number;
  width?: number;
  height?: number;
}

/** Map stress value to RGB color (jet-like: blue→cyan→green→yellow→red) */
function stressColor(seqv: number, vmin: number, vmax: number): [number, number, number] {
  if (vmax <= vmin) return [128, 128, 128];
  let t = (seqv - vmin) / (vmax - vmin);
  t = Math.max(0, Math.min(1, t));
  // Jet colormap approximation
  if (t < 0.125) return [0, 0, Math.round(128 + 127 * (t / 0.125))];
  if (t < 0.375) return [0, Math.round(255 * ((t - 0.125) / 0.25)), 255];
  if (t < 0.625) return [Math.round(255 * ((t - 0.375) / 0.25)), 255, Math.round(255 * (1 - (t - 0.375) / 0.25))];
  if (t < 0.875) return [255, Math.round(255 * (1 - (t - 0.625) / 0.25)), 0];
  return [Math.round(128 + 127 * (1 - (t - 0.875) / 0.125)), 0, 0];
}

/** Simple IDW interpolation for unstructured node data → regular grid */
function interpolateGrid(
  points: StressPoint[],
  rMin: number, rMax: number, zMin: number, zMax: number,
  gridW: number, gridH: number,
): number[][] {
  const grid: number[][] = Array.from({ length: gridH }, () => Array(gridW).fill(NaN));
  const rStep = (rMax - rMin) / (gridW - 1);
  const zStep = (zMax - zMin) / (gridH - 1);

  for (let gy = 0; gy < gridH; gy++) {
    const z = zMin + gy * zStep;
    for (let gx = 0; gx < gridW; gx++) {
      const r = rMin + gx * rStep;
      // IDW: weight = 1/d^2
      let sumW = 0, sumV = 0;
      for (const p of points) {
        const dr = r - p.r_mm;
        const dz = z - p.z_mm;
        const d2 = dr * dr + dz * dz;
        if (d2 < 0.01) { sumV = p.seqv_mpa; sumW = 1; break; }
        const w = 1 / d2;
        sumW += w;
        sumV += w * p.seqv_mpa;
      }
      if (sumW > 0) grid[gy][gx] = sumV / sumW;
    }
  }
  return grid;
}

export default function StressHeatmap({ stressField, discOutline, yieldMpa = 900, width = 400, height = 180 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !stressField.length) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.scale(dpr, dpr);

    // Compute bounds from data
    const rMin = 60, rMax = 250, zMin = -40, zMax = 40;
    const gridW = Math.floor(width / 2);
    const gridH = Math.floor(height / 2);
    const grid = interpolateGrid(stressField, rMin, rMax, zMin, zMax, gridW, gridH);

    // Find vmin/vmax
    let vmin = Infinity, vmax = -Infinity;
    for (const row of grid) for (const v of row) {
      if (!isNaN(v)) { if (v < vmin) vmin = v; if (v > vmax) vmax = v; }
    }
    if (!isFinite(vmin)) { vmin = 0; vmax = 1000; }

    // Draw heatmap cells
    const cw = width / gridW, ch = height / gridH;
    for (let gy = 0; gy < gridH; gy++) {
      for (let gx = 0; gx < gridW; gx++) {
        const v = grid[gy][gx];
        if (isNaN(v)) continue;
        const [cr, cg, cb] = stressColor(v, vmin, vmax);
        ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
        ctx.fillRect(gx * cw, gy * ch, cw + 0.5, ch + 0.5);
      }
    }

    // Disc outline overlay
    if (discOutline && discOutline.length > 0) {
      const toX = (r: number) => (r - rMin) / (rMax - rMin) * width;
      const toY = (z: number) => height - (z - zMin) / (zMax - zMin) * height;
      ctx.beginPath();
      ctx.moveTo(toX(discOutline[0].r_mm), toY(discOutline[0].z_mm));
      for (let i = 1; i < discOutline.length; i++) {
        ctx.lineTo(toX(discOutline[i].r_mm), toY(discOutline[i].z_mm));
      }
      ctx.closePath();
      ctx.strokeStyle = 'rgba(255,255,255,0.8)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Yield line annotation
    if (yieldMpa > vmin && yieldMpa < vmax) {
      const [cyr, cyg, cyb] = stressColor(yieldMpa, vmin, vmax);
      ctx.strokeStyle = `rgb(${cyr},${cyg},${cyb})`;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      // Simplified: draw horizontal yield line at representative Y position
      const yy = height * 0.7;
      ctx.beginPath(); ctx.moveTo(10, yy); ctx.lineTo(width - 10, yy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#fff';
      ctx.font = '9px monospace';
      ctx.fillText(`yield=${yieldMpa}MPa`, width - 130, yy - 4);
    }

    // Colorbar
    const barX = width - 22, barW = 14, barTop = 8, barH = height - 16;
    for (let i = 0; i < barH; i++) {
      const t = 1 - i / barH;
      const val = vmin + t * (vmax - vmin);
      const [cr, cg, cb] = stressColor(val, vmin, vmax);
      ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
      ctx.fillRect(barX, barTop + i, barW, 1);
    }
    ctx.strokeStyle = '#aaa';
    ctx.strokeRect(barX, barTop, barW, barH);
    ctx.fillStyle = '#fff';
    ctx.font = '8px monospace';
    ctx.fillText(`${vmax.toFixed(0)}`, barX + barW + 2, barTop + 8);
    ctx.fillText(`${vmin.toFixed(0)}`, barX + barW + 2, barTop + barH);

    // Axis labels
    ctx.fillStyle = '#aaa';
    ctx.font = '9px monospace';
    ctx.fillText('R(mm) 60', 4, height - 4);
    ctx.fillText('250', width / 2, height - 4);
    ctx.fillText('Z 0', 4, height / 2);
  }, [stressField, discOutline, yieldMpa, width, height]);

  return <canvas ref={canvasRef} className="rounded-lg w-full" style={{ maxWidth: width }} />;
}
