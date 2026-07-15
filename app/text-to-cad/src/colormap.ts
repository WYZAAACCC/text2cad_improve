/**
 * 共享 Jet colormap — Viewport3D / StressHeatmap / ColorbarOverlay 单一来源.
 *
 * 用法:
 *   import { jetColor, jetColorRgb, JET_COLORMAP } from '../colormap';
 *   const [r,g,b] = jetColor(t);        // t∈[0,1], output ∈ [0,255]
 *   const [r,g,b] = jetColorRgb(t);     //                                         t∈[0,1], output ∈ [0,1]
 *   const hex  = JET_COLORMAP.toCss(t); //                                                                   "rgb(r,g,b)"
 */

export type Rgb = [number, number, number];   // [0,255]
export type Rgb01 = [number, number, number]; //  [0,1]

/** value ∈ [0,1] → RGB [0,255] */
export function jetColor(t: number): Rgb {
  t = Math.max(0, Math.min(1, t));
  if (t < 0.125)
    return [0, 0, Math.round(128 + 127 * (t / 0.125))];
  if (t < 0.375)
    return [0, Math.round(255 * ((t - 0.125) / 0.25)), 255];
  if (t < 0.625)
    return [
      Math.round(255 * ((t - 0.375) / 0.25)),
      255,
      Math.round(255 * (1 - (t - 0.375) / 0.25)),
    ];
  if (t < 0.875)
    return [255, Math.round(255 * (1 - (t - 0.625) / 0.25)), 0];
  return [Math.round(128 + 127 * (1 - (t - 0.875) / 0.125)), 0, 0];
}

/** value ∈ [0,1] → RGB [0,1] (Three.js vertex colors) */
export function jetColorRgb(t: number): Rgb01 {
  const [r, g, b] = jetColor(t);
  return [r / 255, g / 255, b / 255];
}

/** HSL for CSS overlays — matches jetColor visually */
function jetColorCss(t: number): string {
  const [r, g, b] = jetColor(t);
  return `rgb(${r},${g},${b})`;
}

export const JET_COLORMAP = {
  color: jetColor,
  colorRgb: jetColorRgb,
  toCss: jetColorCss,
} as const;
