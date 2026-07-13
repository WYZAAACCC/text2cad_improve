/**
 * FEA Tab — RightPanel third tab for finite element analysis
 */
import { useState } from 'react';
import { Play, FlaskConical, Clock, RotateCw } from 'lucide-react';
import { useStore } from '../store';
import { executeFea, pollFeaResult } from '../api';
import StressHeatmap from './StressHeatmap';

export default function FeaTab() {
  const {
    sceneModels, selectedModelId,
    isFeaRunning, feaResult, feaHistory, feaProgress,
    stressColoring, setStressColoring,
    setIsFeaRunning, setFeaResult, addFeaHistory, setFeaProgress,
  } = useStore();

  const [templateName, setTemplateName] = useState('turbine_disc_rotational_thermal');
  const [rpm, setRpm] = useState(5000);
  const [tempRim, setTempRim] = useState(650);
  const [tempBore, setTempBore] = useState(500);

  const stepModels = sceneModels.filter(m => m.type === 'step');

  const handleRunFea = async () => {
    setIsFeaRunning(true);
    setFeaProgress(5);
    try {
      const taskId = await executeFea(templateName, {
        rpm, temp_rim_c: tempRim, temp_bore_c: tempBore,
      });
      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 1500));
        const task = await pollFeaResult(taskId);
        setFeaProgress(Math.max(10, task.progress || 0));
        if (task.status === 'completed' || task.status === 'failed') {
          if (task.result) {
            setFeaResult(task.result);
            if (task.result.stress_field?.length) setStressColoring(true);
            addFeaHistory({
              id: taskId, timestamp: Date.now(), template_name: templateName,
              parameters: { rpm, temp_rim_c: tempRim, temp_bore_c: tempBore },
              result: task.result,
            });
          }
          break;
        }
      }
    } catch (e) {
      console.error('FEA failed:', e);
    } finally {
      setIsFeaRunning(false);
      setFeaProgress(100);
    }
  };

  return (
    <div className="p-4 space-y-4 overflow-y-auto h-full">
      <div className="flex items-center gap-2">
        <FlaskConical className="w-5 h-5 text-accent" />
        <span className="text-sm font-medium text-text-primary">有限元分析</span>
      </div>

      {/* Model selector */}
      <div className="space-y-1">
        <label className="text-xs text-text-muted">分析模型</label>
        <select className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary" value={selectedModelId || ''}>
          <option value="">-- 选择场景中的模型 --</option>
          {stepModels.map(m => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </div>

      {/* Parameters */}
      <div className="space-y-3 bg-bg-tertiary rounded-xl p-3 border border-border">
        <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wide">参数设定</h4>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-text-muted">转速 (RPM)</label>
            <input type="number" value={rpm} onChange={e => setRpm(Number(e.target.value))}
              className="w-full bg-bg-primary border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary" />
          </div>
          <div>
            <label className="text-xs text-text-muted">轮缘温度 (°C)</label>
            <input type="number" value={tempRim} onChange={e => setTempRim(Number(e.target.value))}
              className="w-full bg-bg-primary border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary" />
          </div>
          <div>
            <label className="text-xs text-text-muted">轮毂温度 (°C)</label>
            <input type="number" value={tempBore} onChange={e => setTempBore(Number(e.target.value))}
              className="w-full bg-bg-primary border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary" />
          </div>
          <div>
            <label className="text-xs text-text-muted">模板</label>
            <select value={templateName} onChange={e => setTemplateName(e.target.value)}
              className="w-full bg-bg-primary border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary">
              <option value="turbine_disc_rotational_thermal">涡轮盘 (轴对称)</option>
              <option value="static_cantilever_beam_rect">悬臂梁 (静态)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Run button */}
      <button onClick={handleRunFea} disabled={isFeaRunning || stepModels.length === 0}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-accent text-white rounded-xl text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
        {isFeaRunning ? (
          <><RotateCw className="w-4 h-4 animate-spin" /> 分析中 {feaProgress}%</>
        ) : (
          <><Play className="w-4 h-4" /> 运行有限元分析</>
        )}
      </button>

      {/* Latest result */}
      {feaResult && (
        <div className="bg-bg-tertiary rounded-xl p-3 border border-border">
          <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-2">
            最新分析结果 {feaResult.ok ? '✅' : '❌'}
          </h4>
          <div className="space-y-1 text-xs text-text-primary">
            <div className="flex justify-between"><span>用时</span><span>{feaResult.elapsed_s?.toFixed(1)}s</span></div>
            {Object.entries(feaResult.metrics || {}).slice(0, 5).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-text-muted">{k}</span>
                <span className="font-mono">{typeof v === 'number' ? v.toFixed(1) : String(v)}</span>
              </div>
            ))}
            {feaResult.error && (
              <div className="text-red-400 mt-1 break-all">{feaResult.error.slice(0, 200)}</div>
            )}
          </div>
          {/* Stress field heatmap */}
          {feaResult.stress_field && feaResult.stress_field.length > 0 && (
            <div className="mt-3">
              <h5 className="text-xs text-text-muted mb-1">应力场分布 (Von Mises, MPa)</h5>
              <StressHeatmap
                stressField={feaResult.stress_field}
                yieldMpa={900}
                width={360}
                height={160}
              />
              <button
                onClick={() => setStressColoring(!stressColoring)}
                className={`w-full mt-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  stressColoring ? 'bg-accent text-white' : 'bg-bg-tertiary text-text-secondary border border-border hover:bg-bg-hover'
                }`}
              >
                {stressColoring ? '✅ 3D应力着色 开' : '🎨 开启3D应力着色'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* History */}
      {feaHistory.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-text-secondary uppercase tracking-wide">分析历史</h4>
          {feaHistory.slice().reverse().map(h => (
            <div key={h.id} className="bg-bg-tertiary rounded-lg p-2 border border-border text-xs">
              <div className="flex items-center gap-1 text-text-muted">
                <Clock className="w-3 h-3" />
                {new Date(h.timestamp).toLocaleTimeString()}
                <span className="text-accent ml-auto">{h.result.ok ? 'OK' : 'FAIL'}</span>
              </div>
              <div className="text-text-primary mt-1">
                RPM={String(h.parameters.rpm)}, VMmax={h.result.metrics?.max_von_mises_mpa?.toFixed(0)} MPa
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
