/**
 * 主应用 — 三栏布局 + 空间交互 + Text-to-CAD 生成流程
 */
import { useCallback, useRef, useEffect, useState } from 'react';
import { useStore } from './store';
import { generateModel, pollTaskStatus, startSpatial, continueSpatial } from './api';
import ChatPanel from './components/ChatPanel';
import Viewport3D from './components/Viewport3D';
import RightPanel from './components/RightPanel';
import SpatialModal from './components/SpatialModal';
import type { SpatialQuestion, SpatialAnswer } from './components/SpatialModal';
import type { GenerationTask } from './types';

// Module-level to completely avoid React closure issues
let _pendingText = '';
let _graphKey: string | undefined = undefined;
let _generating = false;
let _spatialSessionId = '';
let _onSpatialQuestions: ((qs: SpatialQuestion[] | null, sid: string, count: number) => void) | null = null;
let _forceRoute: string | undefined = undefined;
export function setForceRoute(route: string | undefined) { _forceRoute = route; }

async function doGenerate(text: string, graphKey?: string) {
  const s = useStore.getState();
  try {
    const taskId = await generateModel(text, s.sessionId, graphKey, _forceRoute);
    let task: GenerationTask | null = null;
    for (let i = 0; i < 120; i++) {
      await new Promise(r => setTimeout(r, 5000));
      task = await pollTaskStatus(taskId);
      s.setGenerationProgress(task.progress || 0);
      if (task.status === 'completed' || task.status === 'failed') break;
    }
    s.setGenerationProgress(100);
    if (task?.status === 'completed' && task.result) {
      // Store for dataset save regardless of success
      s.setLastGenerationResult({
        stepFileUrl: task.result.stepUrl || null,
        stlFileUrl: task.result.stlUrl || null,
        stepFileSize: task.result.stepFileSize,
        userInput: text,
      });
      const stlUrl = task.result.stlUrl || null;
      const stepSize = task.result.stepFileSize || 'N/A';
      const isOk = task.result.ok !== false;
      // Only replace scene if we have actual geometry (STEP file or STL)
      let modelId = '';
      if (stlUrl || (task.result.parameters as any)?.stepKb > 0) {
        s.clearScene();
        const m = s.addSceneModel('step', { stepKb: typeof task.result.parameters?.stepKb === 'number' ? task.result.parameters.stepKb : 0 }, stlUrl);
        modelId = m.id;
      }
      const summary = `已根据需求生成零件：${text.slice(0, 100)}${text.length > 100 ? '...' : ''}`;
      s.addMessage({ role: 'system',
        content: isOk ? `${summary}\nSTEP 文件：${stepSize}${stlUrl ? '，含 3D 预览' : ''}` : `${summary}\nSTEP 文件：${stepSize}（有警告）`,
        modelCard: { modelId, modelName: `零件模型 (${stepSize})`, thumbnailUrl: '', stepFileSize: stepSize, ok: isOk,
                    stepFileUrl: task.result.stepUrl || undefined, stlFileUrl: task.result.stlUrl || undefined } });
    } else if (task?.status === 'failed') {
      s.addMessage({ role: 'system', content: `生成失败：${task.error || '未知错误'}` });
    } else {
      s.addMessage({ role: 'system', content: '生成超时，请重试' });
    }
  } catch (error) {
    console.error('Generation error:', error);
    s.addMessage({ role: 'system', content: `请求失败：${error instanceof Error ? error.message : '网络错误'}` });
  } finally {
    s.setIsGenerating(false);
    _generating = false;
  }
}

async function handleSpatialAnswers(answers: SpatialAnswer[]) {
  if (_onSpatialQuestions) _onSpatialQuestions(null, '', 0); // close modal
  try {
    const result = await continueSpatial(_spatialSessionId, answers);
    if (result.needsClarification && result.questions && _onSpatialQuestions) {
      _onSpatialQuestions(result.questions, result.sessionId || _spatialSessionId, 0);
      _spatialSessionId = result.sessionId || _spatialSessionId;
      return;
    }
    const gk = (result as any).spatialGraphKey;
    if (gk) _graphKey = gk;
    try {
      const h = JSON.parse(localStorage.getItem('spatial_history') || '[]');
      h.unshift({ timestamp: Date.now(), text: _pendingText.slice(0, 200), answers: answers.map(a => ({ questionId: a.questionId, mode: a.mode, selectedOptionId: a.selectedOptionId, customText: a.customText?.slice(0, 200) })), constraintCount: result.constraintCount, assumptions: result.assumptions?.slice(0, 10) });
      localStorage.setItem('spatial_history', JSON.stringify(h.slice(0, 50)));
    } catch { /* */ }
    doGenerate(_pendingText, _graphKey);
  } catch (error) {
    console.error('Spatial continue error:', error);
    doGenerate(_pendingText);
  }
}

async function handleGenerate(text: string) {
  if (_generating) return;
  _generating = true;
  _pendingText = text;
  _graphKey = undefined;
  useStore.getState().setIsGenerating(true);
  try {
    const spatial = await startSpatial(text, 'precision');
    if (spatial.needsClarification && spatial.questions && _onSpatialQuestions) {
      _onSpatialQuestions(spatial.questions, spatial.sessionId || '', spatial.componentCount || 0);
      _spatialSessionId = spatial.sessionId || '';
      return;
    }
    if ((spatial as any).spatialGraphKey) _graphKey = (spatial as any).spatialGraphKey;
  } catch (error) { console.warn('Spatial start failed:', error); }
  doGenerate(text, _graphKey);
}

export default function App() {
  const [spatialQuestions, setSpatialQuestions] = useState<SpatialQuestion[] | null>(null);
  const [spatialSessionId, setSpatialSessionId] = useState<string>('');
  const [spatialComponentCount, setSpatialComponentCount] = useState(0);

  // Wire module-level callbacks to React state
  useEffect(() => {
    _onSpatialQuestions = (qs, sid, count) => { setSpatialQuestions(qs); setSpatialSessionId(sid); setSpatialComponentCount(count); };
    return () => { _onSpatialQuestions = null; };
  }, []);

  const onCancel = useCallback(() => {
    setSpatialQuestions(null);
    _generating = false;
    useStore.getState().setIsGenerating(false);
    doGenerate(_pendingText);
  }, []);

  const handlerRef = useRef(handleGenerate);
  handlerRef.current = handleGenerate;

  useEffect(() => {
    const listener = (e: Event) => { handlerRef.current((e as CustomEvent<string>).detail); };
    window.addEventListener('cad:generate', listener);
    return () => window.removeEventListener('cad:generate', listener);
  }, []);

  return (
    <div className="w-full h-full flex bg-bg-primary">
      <ChatPanel />
      <div className="flex-1 min-w-0"><Viewport3D /></div>
      <RightPanel />
      {spatialQuestions && (
        <SpatialModal questions={spatialQuestions} sessionId={spatialSessionId}
          componentCount={spatialComponentCount} onSubmit={handleSpatialAnswers} onCancel={onCancel} />
      )}
    </div>
  );
}
