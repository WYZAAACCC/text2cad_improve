/**
 * 右侧面板组件
 * 使用 Tab 切换两个视图：属性/图层 和 数据集管理
 * 支持折叠
 */
import { useState, useEffect } from 'react';
import {
  ChevronRight,
  ChevronLeft,
  Layers,
  Database,
  Eye,
  EyeOff,
  Trash2,
  Plus,
  Box,
  Download,
  Copy,
  Search,
  History,
  FlaskConical,
  ChevronDown,
} from 'lucide-react';
import * as Tabs from '@radix-ui/react-tabs';
import * as Dialog from '@radix-ui/react-dialog';
import FeaTab from './FeaTab';
import * as Slider from '@radix-ui/react-slider';
import { useStore } from '../store';
import { getDatasetList, addDatasetEntryApi, deleteDatasetEntryApi } from '../api';
import type { DatasetEntry, SceneModel } from '../types';

// ============================================================
// 属性/图层 Tab
// ============================================================

/** 计算模型体积 */
function calculateVolume(model: SceneModel): number {
  const p = model.parameters as Record<string, number>;
  if (model.type === 'step') return 0; // STL geometry — volume from metadata
  switch (model.type) {
    case 'box': return (p.width || 1) * (p.height || 1) * (p.depth || 1);
    case 'sphere': return (4 / 3) * Math.PI * Math.pow(p.radius || 1, 3);
    case 'cylinder': return Math.PI * Math.pow(p.radius || 1, 2) * (p.length || 2);
    case 'cone': return (1 / 3) * Math.PI * Math.pow(p.radius || 1, 2) * (p.length || 2);
    case 'torus': return 2 * Math.pow(Math.PI, 2) * (p.radius || 2) * Math.pow(p.tube || 0.5, 2);
    default: return 0;
  }
}

/** 计算表面积 */
function calculateSurfaceArea(model: SceneModel): number {
  const p = model.parameters as Record<string, number>;
  if (model.type === 'step') return 0;
  switch (model.type) {
    case 'box': return 2 * ((p.width || 1) * (p.height || 1) + (p.width || 1) * (p.depth || 1) + (p.height || 1) * (p.depth || 1));
    case 'sphere': return 4 * Math.PI * Math.pow(p.radius || 1, 2);
    case 'cylinder': return 2 * Math.PI * (p.radius || 1) * ((p.radius || 1) + (p.length || 2));
    case 'cone': { const slant = Math.sqrt(Math.pow(p.radius || 1, 2) + Math.pow(p.length || 2, 2)); return Math.PI * (p.radius || 1) * ((p.radius || 1) + slant); }
    case 'torus': return 4 * Math.pow(Math.PI, 2) * (p.radius || 2) * (p.tube || 0.5);
    default: return 0;
  }
}

/** 属性滑块组件 */
function ParameterSlider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-text-secondary">{label}</span>
        <span className="text-xs text-text-primary font-mono">{value.toFixed(2)}</span>
      </div>
      <Slider.Root
        className="relative flex items-center select-none touch-none w-full h-5"
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
      >
        <Slider.Track className="bg-bg-tertiary relative grow rounded-full h-1.5">
          <Slider.Range className="absolute bg-accent rounded-full h-full" />
        </Slider.Track>
        <Slider.Thumb
          className="block w-4 h-4 bg-accent rounded-full shadow-lg focus:outline-none focus:ring-2 focus:ring-accent/50 cursor-pointer"
          aria-label={label}
        />
      </Slider.Root>
    </div>
  );
}

/** 空间决策历史 */
function SpatialHistory() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Array<{timestamp: number; text: string; constraintCount?: number; assumptions?: string[]}>>([]);
  useEffect(() => {
    try { setEntries(JSON.parse(localStorage.getItem('spatial_history') || '[]').slice(0, 10)); } catch {}
  }, []);
  if (entries.length === 0) return null;
  return (
    <div className="mb-4 border border-border rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-3 py-2 hover:bg-bg-hover transition-colors">
        <span className="flex items-center gap-1.5 text-xs text-text-secondary">
          <History className="w-3.5 h-3.5" />空间决策历史 ({entries.length})
        </span>
        <ChevronDown className={`w-3.5 h-3.5 text-text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="border-t border-border max-h-48 overflow-y-auto">
          {entries.map((e, i) => (
            <div key={i} className="px-3 py-2 border-b border-border last:border-b-0 text-xs">
              <p className="text-text-primary truncate">{e.text}</p>
              <p className="text-text-muted mt-0.5">{new Date(e.timestamp).toLocaleString()} · {e.constraintCount || 0} constraints</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 属性/图层面板 */
function PropertiesTab() {
  const {
    sceneModels,
    selectedModelId,
    setSelectedModel,
    updateModelParameter,
    toggleModelVisibility,
    removeSceneModel,
  } = useStore();

  const selectedModel = sceneModels.find((m) => m.id === selectedModelId);

  return (
    <div className="flex flex-col h-full">
      {/* 选中模型属性 */}
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-medium text-text-primary mb-3">模型属性</h3>

        {selectedModel ? (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: selectedModel.color }}
              />
              <span className="text-sm text-text-primary">{selectedModel.name}</span>
            </div>

            {/* 参数滑块 */}
            {selectedModel.type === 'box' && (
              <>
                <ParameterSlider label="宽度"
                  value={(selectedModel.parameters as Record<string,number>).width || 1}
                  min={0.1} max={10} step={0.1}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'width', v)} />
                <ParameterSlider label="高度"
                  value={(selectedModel.parameters as Record<string,number>).height || 1}
                  min={0.1} max={10} step={0.1}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'height', v)} />
                <ParameterSlider label="深度"
                  value={(selectedModel.parameters as Record<string,number>).depth || 1}
                  min={0.1} max={10} step={0.1}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'depth', v)} />
              </>
            )}

            {(selectedModel.type === 'sphere' || selectedModel.type === 'cylinder' || selectedModel.type === 'cone') && (
              <>
                <ParameterSlider label="半径"
                  value={(selectedModel.parameters as Record<string,number>).radius || 1}
                  min={0.1} max={5} step={0.1}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'radius', v)} />
                {(selectedModel.type === 'cylinder' || selectedModel.type === 'cone') && (
                  <ParameterSlider label="高度"
                    value={(selectedModel.parameters as Record<string,number>).length || 2}
                    min={0.1} max={10} step={0.1}
                    onChange={(v) => updateModelParameter(selectedModel.id, 'length', v)} />
                )}
              </>
            )}

            {selectedModel.type === 'torus' && (
              <>
                <ParameterSlider label="主半径"
                  value={(selectedModel.parameters as Record<string,number>).radius || 2}
                  min={0.5} max={5}
                  step={0.1}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'radius', v)}
                />
                <ParameterSlider label="管道半径"
                  value={(selectedModel.parameters as Record<string,number>).tube || 0.5}
                  min={0.1} max={2} step={0.05}
                  onChange={(v) => updateModelParameter(selectedModel.id, 'tube', v)} />
              </>
            )}

            {/* step 模型属性 */}
            {selectedModel.type === 'step' && (
              <div className="space-y-2 mb-3">
                <div className="flex justify-between text-xs">
                  <span className="text-text-secondary">类型</span>
                  <span className="text-text-primary">STEP CAD 模型</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-text-secondary">STEP 大小</span>
                  <span className="text-text-primary font-mono">{(selectedModel.parameters as any).stepKb || 0} KB</span>
                </div>
                {selectedModel.stlUrl && (
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">STL 预览</span>
                    <span className="text-accent">可用</span>
                  </div>
                )}
              </div>
            )}

            {/* 计算属性 */}
            {selectedModel.type !== 'step' && (
            <div className="mt-4 pt-3 border-t border-border space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-text-secondary">体积</span>
                <span className="text-text-primary font-mono">
                  {calculateVolume(selectedModel).toFixed(2)} m³
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-secondary">表面积</span>
                <span className="text-text-primary font-mono">
                  {calculateSurfaceArea(selectedModel).toFixed(2)} m²
                </span>
              </div>
            </div>
            )}
          </div>
        ) : (
          <div className="text-center py-6 text-text-muted">
            <Box className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-xs">点击场景中的模型查看属性</p>
          </div>
        )}
      </div>

      {/* 图层列表 */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <h3 className="text-sm font-medium text-text-primary mb-3">图层列表</h3>

        <SpatialHistory />

        {sceneModels.length === 0 ? (
          <p className="text-xs text-text-muted text-center py-4">场景中暂无模型</p>
        ) : (
          <div className="space-y-2">
            {sceneModels.map((model) => (
              <div
                key={model.id}
                onClick={() => setSelectedModel(model.id)}
                className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-colors ${
                  model.id === selectedModelId
                    ? 'bg-accent/10 border border-accent/30'
                    : 'hover:bg-bg-hover border border-transparent'
                }`}
              >
                <div
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: model.color }}
                />
                <span className="flex-1 text-xs text-text-primary truncate">
                  {model.name}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleModelVisibility(model.id);
                  }}
                  className="p-1 rounded hover:bg-bg-hover text-text-muted transition-colors"
                  title={model.visible ? '隐藏' : '显示'}
                >
                  {model.visible ? (
                    <Eye className="w-3.5 h-3.5" />
                  ) : (
                    <EyeOff className="w-3.5 h-3.5" />
                  )}
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeSceneModel(model.id);
                  }}
                  className="p-1 rounded hover:bg-bg-hover text-text-muted hover:text-danger transition-colors"
                  title="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// 数据集管理 Tab
// ============================================================

/** 添加数据集弹窗 */
function AddDatasetDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (name: string, tags: string[]) => void;
}) {
  const [name, setName] = useState('');
  const [tagsText, setTagsText] = useState('');

  const handleSubmit = () => {
    if (!name.trim()) return;
    const tags = tagsText
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean);
    onConfirm(name.trim(), tags);
    setName('');
    setTagsText('');
    onOpenChange(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-bg-secondary border border-border rounded-xl p-6 w-96 z-50 shadow-2xl">
          <Dialog.Title className="text-base font-medium text-text-primary mb-4">
            添加到数据集
          </Dialog.Title>

          <div className="space-y-4">
            <div>
              <label className="block text-xs text-text-secondary mb-1.5">名称</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="输入模型名称"
                className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted outline-none focus:border-accent transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs text-text-secondary mb-1.5">
                标签（用逗号分隔）
              </label>
              <input
                type="text"
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
                placeholder="例如：机械, 齿轮, 精密"
                className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted outline-none focus:border-accent transition-colors"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 mt-6">
            <button
              onClick={() => onOpenChange(false)}
              className="px-4 py-2 rounded-lg text-sm text-text-secondary hover:bg-bg-hover transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!name.trim()}
              className="px-4 py-2 rounded-lg text-sm bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              添加
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** 数据集详情面板 */
function DatasetDetail({ entry }: { entry: DatasetEntry }) {
  const [activeSubTab, setActiveSubTab] = useState('userInput');
  const [copied, setCopied] = useState(false);

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const tabs = [
    { id: 'userInput', label: '用户输入' },
    { id: 'featureGraph', label: 'FeatureGraph' },
    { id: 'gcadDocument', label: 'GCAD文档' },
    { id: 'cadQueryCode', label: 'CADQuery' },
    { id: 'stepFile', label: 'STEP文件' },
    { id: 'solveResult', label: '求解结果' },
  ];

  const renderContent = () => {
    switch (activeSubTab) {
      case 'userInput':
        return (
          <div>
            <p className="text-sm text-text-primary leading-relaxed">{entry.data.userInput}</p>
            <button
              onClick={() => handleCopy(entry.data.userInput)}
              className="mt-3 flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover transition-colors"
            >
              <Copy className="w-3.5 h-3.5" />
              {copied ? '已复制' : '复制文本'}
            </button>
          </div>
        );

      case 'featureGraph':
        return (
          <div className="space-y-3">
            <div>
              <h4 className="text-xs text-text-secondary mb-2">节点</h4>
              <div className="space-y-1.5">
                {entry.data.featureGraph.nodes.map((node) => (
                  <div
                    key={node.id}
                    className="bg-bg-tertiary rounded-lg px-3 py-2 text-xs"
                  >
                    <span className="text-accent font-medium">{node.id}</span>
                    <span className="text-text-secondary mx-2">·</span>
                    <span className="text-text-primary">{node.type}</span>
                    <div className="mt-1 text-text-muted">
                      {JSON.stringify(node.params)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h4 className="text-xs text-text-secondary mb-2">边</h4>
              <div className="space-y-1.5">
                {entry.data.featureGraph.edges.map((edge, i) => (
                  <div
                    key={i}
                    className="bg-bg-tertiary rounded-lg px-3 py-2 text-xs flex items-center gap-2"
                  >
                    <span className="text-text-primary">{edge.from}</span>
                    <span className="text-accent">→</span>
                    <span className="text-text-primary">{edge.to}</span>
                    <span className="text-text-muted">({edge.relation})</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        );

      case 'gcadDocument':
        return (
          <div>
            <pre className="text-xs overflow-x-auto">{entry.data.gcadDocument}</pre>
            <button
              onClick={() => {
                const blob = new Blob([entry.data.gcadDocument], { type: 'text/xml' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${entry.name}.gcad`;
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="mt-3 flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              下载 GCAD 文档
            </button>
          </div>
        );

      case 'cadQueryCode':
        return (
          <div>
            <pre className="text-xs overflow-x-auto">{entry.data.cadQueryCode}</pre>
            <button
              onClick={() => handleCopy(entry.data.cadQueryCode)}
              className="mt-3 flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover transition-colors"
            >
              <Copy className="w-3.5 h-3.5" />
              {copied ? '已复制' : '复制代码'}
            </button>
          </div>
        );

      case 'stepFile':
        return (
          <div className="text-center py-4">
            <Box className="w-10 h-10 mx-auto mb-3 text-text-muted" />
            <p className="text-sm text-text-primary mb-1">{entry.name}.step</p>
            <p className="text-xs text-text-muted mb-1">文件大小: {entry.data.stepFileSize || 'N/A'}</p>
            {(entry.data as any).stlFileUrl && <p className="text-xs text-accent mb-3">STL 预览可用</p>}
            {entry.data.stepFileUrl ? (
              <a href={entry.data.stepFileUrl} download={`${entry.name}.step`}
                className="inline-flex items-center gap-1.5 px-4 py-2 bg-accent text-white rounded-lg text-sm hover:bg-accent-hover transition-colors">
                <Download className="w-4 h-4" />下载 STEP 文件
              </a>
            ) : (
              <p className="text-xs text-text-muted">暂无 STEP 文件</p>
            )}
          </div>
        );

      case 'solveResult': {
        const r = entry.data.solveResult as any;
        return (
          <div className="space-y-2">
            {[
              { label: '体积', value: `${r.volume?.toFixed(2) ?? 'N/A'} mm³` },
              { label: '表面积', value: `${r.surfaceArea?.toFixed(2) ?? 'N/A'} mm²` },
              { label: '质心', value: `(${r.centroid?.join(', ') ?? 'N/A'})` },
              { label: '质量', value: `${r.mass?.toFixed(2) ?? 'N/A'} g` },
              { label: '密度', value: `${r.density ?? 'N/A'} kg/m³` },
              { label: '包围盒', value: r.boundingBox ? `min(${r.boundingBox.min?.join(', ')}), max(${r.boundingBox.max?.join(', ')})` : 'N/A' },
            ].map((item) => (
              <div
                key={item.label}
                className="flex justify-between items-center bg-bg-tertiary rounded-lg px-3 py-2"
              >
                <span className="text-xs text-text-secondary">{item.label}</span>
                <span className="text-xs text-text-primary font-mono">{item.value}</span>
              </div>
            ))}
          </div>
        );
      }

      default:
        return null;
    }
  };

  return (
    <div className="border-t border-border">
      {/* 子标签页 */}
      <div className="flex overflow-x-auto border-b border-border scrollbar-hide">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveSubTab(tab.id)}
            className={`px-3 py-2 text-xs whitespace-nowrap transition-colors ${
              activeSubTab === tab.id
                ? 'text-accent border-b-2 border-accent'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="p-4">{renderContent()}</div>
    </div>
  );
}

/** 数据集管理面板 */
function DatasetTab() {
  const {
    datasetEntries,
    selectedDatasetEntryId,
    setSelectedDatasetEntry,
    addDatasetEntry,
    removeDatasetEntry,
    clearScene,
    addSceneModel,
  } = useStore();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // 过滤数据集
  const filteredEntries = datasetEntries.filter(
    (entry) =>
      entry.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      entry.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  // 从后端加载数据集
  useEffect(() => {
    getDatasetList().then((entries) => {
      if (entries.length > 0) {
        useStore.setState({ datasetEntries: entries });
      }
    }).catch(() => { /* server unavailable */ });
  }, []);

  // 添加当前设计到数据集 — 使用真实生成结果
  const handleAddToDataset = async (name: string, tags: string[]) => {
    const result = useStore.getState().lastGenerationResult;
    if (!result) return;

    const entryData: Record<string, unknown> = {};
    if (result.stepFileUrl) entryData.stepFileUrl = result.stepFileUrl;
    if (result.stlFileUrl) entryData.stlFileUrl = result.stlFileUrl;
    if (result.stepFileSize) entryData.stepFileSize = result.stepFileSize;

    try {
      const newEntry = await addDatasetEntryApi({ name, tags, data: entryData } as any);
      addDatasetEntry({ name: newEntry.name, thumbnailUrl: '', tags: newEntry.tags, data: newEntry.data });
    } catch {
      // Fallback: save locally if server unavailable
      addDatasetEntry({ name, thumbnailUrl: '', tags, data: entryData as any });
    }
  };

  // 加载到场景 — 使用真实 STL URL
  const handleLoadToScene = (entry: DatasetEntry) => {
    clearScene();
    const stlUrl = (entry.data as unknown as Record<string, unknown>).stlFileUrl as string | undefined;
    const stepKb = parseInt(((entry.data as unknown as Record<string, unknown>).stepFileSize as string) || '0') || 0;
    addSceneModel('step', { stepKb }, stlUrl || null);
  };

  const selectedEntry = datasetEntries.find((e) => e.id === selectedDatasetEntryId);

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="px-4 py-3 border-b border-border space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-text-primary">数据集</h3>
          <button
            onClick={() => setDialogOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-xs hover:bg-accent-hover transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            添加当前设计
          </button>
        </div>

        {/* 搜索框 */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索数据集..."
            className="w-full bg-bg-tertiary border border-border rounded-lg pl-8 pr-3 py-2 text-xs text-text-primary placeholder-text-muted outline-none focus:border-accent transition-colors"
          />
        </div>
      </div>

      {/* 数据集网格 */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {filteredEntries.length === 0 ? (
          <div className="text-center py-8 text-text-muted">
            <Database className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-xs">暂无数据集条目</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {filteredEntries.map((entry) => (
              <div
                key={entry.id}
                onClick={() => setSelectedDatasetEntry(entry.id)}
                onDoubleClick={() => handleLoadToScene(entry)}
                className={`relative bg-bg-tertiary border rounded-xl overflow-hidden cursor-pointer transition-all ${
                  entry.id === selectedDatasetEntryId
                    ? 'border-accent ring-1 ring-accent/30'
                    : 'border-border hover:border-border-light'
                }`}
              >
                <img
                  src={entry.thumbnailUrl}
                  alt={entry.name}
                  className="w-full aspect-square object-cover"
                />
                <div className="p-2">
                  <p className="text-xs text-text-primary font-medium truncate">
                    {entry.name}
                  </p>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {entry.tags.slice(0, 2).map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] px-1.5 py-0.5 bg-bg-hover text-text-secondary rounded"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                {/* 删除按钮 */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteDatasetEntryApi(entry.id).catch(() => {});
                    removeDatasetEntry(entry.id);
                  }}
                  className="absolute top-1.5 right-1.5 p-1 rounded bg-bg-secondary/80 text-text-muted hover:text-danger transition-colors opacity-0 group-hover:opacity-100"
                  style={{ opacity: 1 }}
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 详情面板 */}
      {selectedEntry && (
        <div className="border-t border-border max-h-80 overflow-y-auto">
          <div className="px-4 py-2 border-b border-border flex items-center justify-between">
            <span className="text-sm font-medium text-text-primary">{selectedEntry.name}</span>
            <button
              onClick={() => handleLoadToScene(selectedEntry)}
              className="flex items-center gap-1.5 px-3 py-1 bg-accent text-white rounded-lg text-xs hover:bg-accent-hover transition-colors"
            >
              <Box className="w-3 h-3" />
              加载到场景
            </button>
          </div>
          <DatasetDetail entry={selectedEntry} />
        </div>
      )}

      <AddDatasetDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onConfirm={handleAddToDataset}
      />
    </div>
  );
}

// ============================================================
// 主右侧面板
// ============================================================

export default function RightPanel() {
  const { rightPanelCollapsed, setRightPanelCollapsed, rightPanelActiveTab, setRightPanelActiveTab } = useStore();

  if (rightPanelCollapsed) {
    return (
      <div className="w-10 bg-bg-secondary border-l border-border flex flex-col items-center py-3 flex-shrink-0">
        <button
          onClick={() => setRightPanelCollapsed(false)}
          className="p-2 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors"
          title="展开右侧面板"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <div className="mt-4">
          <Layers className="w-5 h-5 text-text-muted" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 bg-bg-secondary border-l border-border flex flex-col flex-shrink-0">
      <Tabs.Root
        value={rightPanelActiveTab}
        onValueChange={(v) => setRightPanelActiveTab(v as 'properties' | 'dataset')}
        className="flex flex-col h-full"
      >
        {/* Tab 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <Tabs.List className="flex items-center gap-1 bg-bg-tertiary rounded-lg p-0.5">
            <Tabs.Trigger
              value="properties"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all data-[state=active]:bg-bg-hover data-[state=active]:text-text-primary text-text-secondary"
            >
              <Layers className="w-3.5 h-3.5" />
              属性/图层
            </Tabs.Trigger>
            <Tabs.Trigger
              value="dataset"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all data-[state=active]:bg-bg-hover data-[state=active]:text-text-primary text-text-secondary"
            >
              <Database className="w-3.5 h-3.5" />
              数据集
            </Tabs.Trigger>
            <Tabs.Trigger
              value="fea"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all data-[state=active]:bg-bg-hover data-[state=active]:text-text-primary text-text-secondary"
            >
              <FlaskConical className="w-3.5 h-3.5" />
              FEA
            </Tabs.Trigger>
          </Tabs.List>

          <button
            onClick={() => setRightPanelCollapsed(true)}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors"
            title="折叠面板"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Tab 内容 */}
        <Tabs.Content value="properties" className="flex-1 overflow-hidden data-[state=inactive]:hidden">
          <PropertiesTab />
        </Tabs.Content>
        <Tabs.Content value="dataset" className="flex-1 overflow-hidden data-[state=inactive]:hidden">
          <DatasetTab />
        </Tabs.Content>
        <Tabs.Content value="fea" className="flex-1 overflow-hidden data-[state=inactive]:hidden">
          <FeaTab />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
