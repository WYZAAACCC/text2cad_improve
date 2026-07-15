/**
 * 颜色条图例覆盖层 — HTML div, 与 colormap.ts 和 stressWorker.ts 同源 jet.
 */
import { JET_COLORMAP } from '../colormap';

interface Props {
  vmin: number; vmax: number; unit: string;
  yieldVal?: number;  // 屈服线标注 (MPa), omit for no annotation
  visible: boolean;
}

export default function ColorbarOverlay({ vmin, vmax, unit, yieldVal, visible }: Props) {
  if (!visible || !isFinite(vmin) || !isFinite(vmax) || vmax <= vmin) return null;

  const steps = 64;
  const gradientStops = Array.from({ length: steps }, (_, i) => {
    const t = 1 - i / (steps - 1);
    return JET_COLORMAP.toCss(t);
  }).join(',\n');

  const vmid = (vmin + vmax) / 2;

  return (
    <div className="absolute right-4 top-1/2 -translate-y-1/2 z-10 flex items-center gap-2
                    bg-bg-secondary/80 backdrop-blur-sm rounded-lg px-2 py-3 shadow-lg">
      {/* 刻度标签 */}
      <div className="flex flex-col justify-between h-40 text-xs text-text-secondary font-mono">
        <span>{vmax.toFixed(0)}</span>
        <span>{vmid.toFixed(0)}</span>
        <span>{vmin.toFixed(0)}</span>
      </div>
      {/* 渐变色条 */}
      <div
        className="w-4 h-40 rounded-sm border border-border relative"
        style={{ background: `linear-gradient(to bottom, ${gradientStops})` }}
      >
        {yieldVal !== undefined && yieldVal > vmin && yieldVal < vmax && (
          <div
            className="absolute left-0 right-0 border-t border-dashed border-white/70"
            style={{
              top: `${((vmax - yieldVal) / (vmax - vmin)) * 100}%`,
            }}
            title={`yield=${yieldVal} ${unit}`}
          />
        )}
      </div>
      {/* 单位 */}
      <span className="text-xs text-text-muted font-mono">{unit}</span>
    </div>
  );
}
