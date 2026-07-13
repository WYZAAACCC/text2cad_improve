/**
 * Zustand 状态管理
 * 管理应用全局状态：对话、场景模型、数据集、选中状态等
 */
import { create } from 'zustand';
import type {
  ChatMessage,
  SceneModel,
  DatasetEntry,
  GeometryType,
  ModelParameters,
} from './types';

/** 生成唯一 ID */
function generateId(): string {
  return Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
}

/** 创建默认模型 */
function createDefaultModel(
  type: GeometryType | 'step' = 'box',
  params: ModelParameters | Record<string, unknown> = { width: 2, height: 2, depth: 2 },
  stlUrl: string | null = null
): SceneModel {
  const colors: Record<string, string> = {
    box: '#4f8cff', sphere: '#ff6b6b', cylinder: '#51cf66',
    cone: '#fcc419', torus: '#cc5de8', step: '#58a6ff',
  };

  const names: Record<string, string> = {
    box: '立方体', sphere: '球体', cylinder: '圆柱体', cone: '圆锥体', torus: '圆环体', step: 'CAD Model',
  };

  return {
    id: generateId(),
    name: names[type] || 'Model',
    type: type as SceneModel['type'],
    visible: true,
    position: [0, 0, 0],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    parameters: params as SceneModel['parameters'],
    color: colors[type] || '#58a6ff',
    stlUrl,
  };
}

/** 应用状态接口 */
interface AppState {
  // 对话状态
  messages: ChatMessage[];
  sessionId: string;
  isGenerating: boolean;

  // 场景模型状态
  sceneModels: SceneModel[];
  selectedModelId: string | null;

  // 数据集状态
  datasetEntries: DatasetEntry[];
  selectedDatasetEntryId: string | null;

  // 最近生成结果（供数据集保存使用）
  lastGenerationResult: {
    stepFileUrl?: string | null;
    stlFileUrl?: string | null;
    stepFileSize?: string;
    userInput?: string;
  } | null;
  setLastGenerationResult: (r: AppState['lastGenerationResult']) => void;

  // 生成进度
  generationProgress: number;
  generationStage: string;
  setGenerationProgress: (p: number, stage?: string) => void;

  // UI 状态
  leftPanelCollapsed: boolean;
  rightPanelCollapsed: boolean;
  rightPanelActiveTab: 'properties' | 'dataset' | 'fea';
  wireframeMode: boolean;

  // FEA State
  feaResult: import('./types').FeaResult | null;
  feaHistory: import('./types').FeaHistoryEntry[];
  isFeaRunning: boolean;
  feaProgress: number;
  highlightedRegionId: string | null;
  feaRegions: import('./types').FeaRegionDef[];
  stressColoring: boolean;

  setFeaResult: (r: import('./types').FeaResult | null) => void;
  addFeaHistory: (entry: import('./types').FeaHistoryEntry) => void;
  setIsFeaRunning: (v: boolean) => void;
  setFeaProgress: (p: number) => void;
  setHighlightedRegion: (id: string | null) => void;
  setFeaRegions: (regions: import('./types').FeaRegionDef[]) => void;
  setStressColoring: (v: boolean) => void;

  // Actions
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  clearMessages: () => void;
  setIsGenerating: (value: boolean) => void;

  addSceneModel: (type: GeometryType | 'step', params?: ModelParameters | Record<string, unknown>, stlUrl?: string | null) => SceneModel;
  removeSceneModel: (id: string) => void;
  updateSceneModel: (id: string, updates: Partial<SceneModel>) => void;
  updateModelParameter: (id: string, param: string, value: number) => void;
  setSelectedModel: (id: string | null) => void;
  toggleModelVisibility: (id: string) => void;
  clearScene: () => void;

  addDatasetEntry: (entry: Omit<DatasetEntry, 'id' | 'createdAt'>) => DatasetEntry;
  removeDatasetEntry: (id: string) => void;
  setSelectedDatasetEntry: (id: string | null) => void;

  setLeftPanelCollapsed: (value: boolean) => void;
  setRightPanelCollapsed: (value: boolean) => void;
  setRightPanelActiveTab: (tab: 'properties' | 'dataset') => void;
  setWireframeMode: (value: boolean) => void;
}

/** 预置数据集 */
const presetDataset: DatasetEntry[] = [
  {
    id: 'preset-1',
    name: '机械齿轮',
    thumbnailUrl: 'https://placehold.co/120x120/2a2a32/4f8cff?text=Gear',
    tags: ['机械', '齿轮', '精密'],
    createdAt: Date.now() - 86400000 * 3,
    data: {
      userInput: '生成一个模数为2、齿数为20的直齿圆柱齿轮',
      featureGraph: {
        nodes: [
          { id: 'n1', type: 'Cylinder', params: { radius: 20, height: 10 } },
          { id: 'n2', type: 'TeethPattern', params: { count: 20, module: 2 } },
        ],
        edges: [{ from: 'n1', to: 'n2', relation: 'apply' }],
      },
      gcadDocument: `<?xml version="1.0" encoding="UTF-8"?>
<GCADDocument version="1.0">
  <Feature id="base_cylinder" type="Cylinder">
    <Parameter name="radius" value="20"/>
    <Parameter name="height" value="10"/>
  </Feature>
  <Feature id="teeth" type="TeethPattern">
    <Parameter name="count" value="20"/>
    <Parameter name="module" value="2"/>
  </Feature>
</GCADDocument>`,
      cadQueryCode: `import cadquery as cq

# 创建齿轮主体
result = cq.Workplane("XY")
    .circle(20)
    .extrude(10)

# 添加齿形
result = result.faces(">Z").workplane()
    .gearShape(module=2, teeth=20)
    .extrude(10)

show_object(result)`,
      stepFileUrl: '/mock/gear_20m2.step',
      stepFileSize: '156 KB',
      solveResult: {
        volume: 12566.37,
        surfaceArea: 2513.27,
        centroid: [0, 0, 5],
        boundingBox: { min: [-22, -22, 0], max: [22, 22, 10] },
        mass: 98.7,
        density: 7850,
      },
    },
  },
  {
    id: 'preset-2',
    name: '连接法兰',
    thumbnailUrl: 'https://placehold.co/120x120/2a2a32/51cf66?text=Flange',
    tags: ['管道', '法兰', '连接件'],
    createdAt: Date.now() - 86400000 * 5,
    data: {
      userInput: '生成一个DN50的法兰盘，带8个螺栓孔',
      featureGraph: {
        nodes: [
          { id: 'n1', type: 'Cylinder', params: { radius: 60, height: 15 } },
          { id: 'n2', type: 'HolePattern', params: { count: 8, radius: 45, holeRadius: 8 } },
          { id: 'n3', type: 'Bore', params: { radius: 25 } },
        ],
        edges: [
          { from: 'n1', to: 'n2', relation: 'subtract' },
          { from: 'n1', to: 'n3', relation: 'subtract' },
        ],
      },
      gcadDocument: `<?xml version="1.0" encoding="UTF-8"?>
<GCADDocument version="1.0">
  <Feature id="flange_body" type="Cylinder">
    <Parameter name="radius" value="60"/>
    <Parameter name="height" value="15"/>
  </Feature>
  <Feature id="bolt_holes" type="HolePattern">
    <Parameter name="count" value="8"/>
    <Parameter name="radius" value="45"/>
    <Parameter name="holeRadius" value="8"/>
  </Feature>
  <Feature id="center_bore" type="Bore">
    <Parameter name="radius" value="25"/>
  </Feature>
</GCADDocument>`,
      cadQueryCode: `import cadquery as cq

# 法兰主体
flange = cq.Workplane("XY").circle(60).extrude(15)

# 螺栓孔
holes = flange.faces(">Z").workplane()
    .polarArray(45, 0, 360, 8)
    .circle(8).cutThruAll()

# 中心孔
result = holes.faces(">Z").workplane()
    .circle(25).cutThruAll()

show_object(result)`,
      stepFileUrl: '/mock/flange_dn50.step',
      stepFileSize: '89 KB',
      solveResult: {
        volume: 145200.0,
        surfaceArea: 18450.0,
        centroid: [0, 0, 7.5],
        boundingBox: { min: [-60, -60, 0], max: [60, 60, 15] },
        mass: 1139.8,
        density: 7850,
      },
    },
  },
  {
    id: 'preset-3',
    name: '支架底座',
    thumbnailUrl: 'https://placehold.co/120x120/2a2a32/fcc419?text=Bracket',
    tags: ['结构', '支架', '支撑'],
    createdAt: Date.now() - 86400000 * 7,
    data: {
      userInput: '生成一个L型支架底座，带加强筋',
      featureGraph: {
        nodes: [
          { id: 'n1', type: 'Box', params: { width: 100, height: 10, depth: 60 } },
          { id: 'n2', type: 'Box', params: { width: 10, height: 80, depth: 60 } },
          { id: 'n3', type: 'Fillet', params: { radius: 5 } },
        ],
        edges: [
          { from: 'n1', to: 'n2', relation: 'union' },
          { from: 'n1', to: 'n3', relation: 'apply' },
        ],
      },
      gcadDocument: `<?xml version="1.0" encoding="UTF-8"?>
<GCADDocument version="1.0">
  <Feature id="base" type="Box">
    <Parameter name="width" value="100"/>
    <Parameter name="height" value="10"/>
    <Parameter name="depth" value="60"/>
  </Feature>
  <Feature id="vertical" type="Box">
    <Parameter name="width" value="10"/>
    <Parameter name="height" value="80"/>
    <Parameter name="depth" value="60"/>
  </Feature>
  <Feature id="fillet" type="Fillet">
    <Parameter name="radius" value="5"/>
  </Feature>
</GCADDocument>`,
      cadQueryCode: `import cadquery as cq

# 底座
base = cq.Workplane("XY").box(100, 60, 10)

# 垂直板
vertical = cq.Workplane("XY").box(10, 60, 80)
    .translate((45, 0, 35))

# 合并
result = base.union(vertical)

# 圆角
result = result.edges().fillet(5)

show_object(result)`,
      stepFileUrl: '/mock/bracket_base.step',
      stepFileSize: '67 KB',
      solveResult: {
        volume: 108000.0,
        surfaceArea: 32400.0,
        centroid: [22.5, 0, 22.5],
        boundingBox: { min: [-50, -30, 0], max: [50, 30, 80] },
        mass: 847.8,
        density: 7850,
      },
    },
  },
];

/** 预置对话消息 */
const presetMessages: ChatMessage[] = [
  {
    id: generateId(),
    role: 'system',
    content: '欢迎使用智能建模平台！请用自然语言描述你要设计的零件。',
    timestamp: Date.now() - 86400000,
  },
];

export const useStore = create<AppState>((set) => ({
  // 初始状态
  messages: [...presetMessages],
  sessionId: generateId(),
  isGenerating: false,
  sceneModels: [createDefaultModel('box', { width: 2, height: 2, depth: 2 })],
  selectedModelId: null,
  datasetEntries: [...presetDataset],
  selectedDatasetEntryId: null,
  lastGenerationResult: null,
  setLastGenerationResult: (r) => set(() => ({ lastGenerationResult: r })),

  generationProgress: 0,
  generationStage: '',
  setGenerationProgress: (p, s) => set(() => ({ generationProgress: p, generationStage: s || '' })),

  leftPanelCollapsed: false,
  rightPanelCollapsed: false,
  rightPanelActiveTab: 'properties',
  wireframeMode: false,

  // 对话 Actions
  addMessage: (message) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          ...message,
          id: generateId(),
          timestamp: Date.now(),
        },
      ],
    })),

  clearMessages: () =>
    set(() => ({
      messages: [],
      sessionId: generateId(),
    })),

  setIsGenerating: (value) => set(() => ({ isGenerating: value })),

  // 场景模型 Actions
  addSceneModel: (type, params, stlUrl) => {
    const model = createDefaultModel(type, params, stlUrl);
    set((state) => ({
      sceneModels: [...state.sceneModels, model],
      selectedModelId: model.id,
    }));
    return model;
  },

  removeSceneModel: (id) =>
    set((state) => ({
      sceneModels: state.sceneModels.filter((m) => m.id !== id),
      selectedModelId: state.selectedModelId === id ? null : state.selectedModelId,
    })),

  updateSceneModel: (id, updates) =>
    set((state) => ({
      sceneModels: state.sceneModels.map((m) =>
        m.id === id ? { ...m, ...updates } : m
      ),
    })),

  updateModelParameter: (id, param, value) =>
    set((state) => ({
      sceneModels: state.sceneModels.map((m) =>
        m.id === id
          ? { ...m, parameters: { ...m.parameters, [param]: value } }
          : m
      ),
    })),

  setSelectedModel: (id) => set(() => ({ selectedModelId: id })),

  toggleModelVisibility: (id) =>
    set((state) => ({
      sceneModels: state.sceneModels.map((m) =>
        m.id === id ? { ...m, visible: !m.visible } : m
      ),
    })),

  clearScene: () =>
    set(() => ({
      sceneModels: [],
      selectedModelId: null,
    })),

  // 数据集 Actions
  addDatasetEntry: (entry) => {
    const newEntry: DatasetEntry = {
      ...entry,
      id: generateId(),
      createdAt: Date.now(),
    };
    set((state) => ({
      datasetEntries: [...state.datasetEntries, newEntry],
    }));
    return newEntry;
  },

  removeDatasetEntry: (id) =>
    set((state) => ({
      datasetEntries: state.datasetEntries.filter((e) => e.id !== id),
      selectedDatasetEntryId:
        state.selectedDatasetEntryId === id ? null : state.selectedDatasetEntryId,
    })),

  setSelectedDatasetEntry: (id) => set(() => ({ selectedDatasetEntryId: id })),

  // UI Actions
  setLeftPanelCollapsed: (value) => set(() => ({ leftPanelCollapsed: value })),
  setRightPanelCollapsed: (value) => set(() => ({ rightPanelCollapsed: value })),
  setRightPanelActiveTab: (tab) => set(() => ({ rightPanelActiveTab: tab })),
  setWireframeMode: (value) => set(() => ({ wireframeMode: value })),

  // FEA initial state
  feaResult: null,
  feaHistory: [],
  isFeaRunning: false,
  feaProgress: 0,
  highlightedRegionId: null,
  feaRegions: [],
  stressColoring: false,

  setFeaResult: (r) => set(() => ({ feaResult: r })),
  addFeaHistory: (entry) => set((s) => ({ feaHistory: [...s.feaHistory, entry] })),
  setIsFeaRunning: (v) => set(() => ({ isFeaRunning: v })),
  setFeaProgress: (p) => set(() => ({ feaProgress: p })),
  setHighlightedRegion: (id) => set(() => ({ highlightedRegionId: id })),
  setFeaRegions: (regions) => set(() => ({ feaRegions: regions })),
  setStressColoring: (v) => set(() => ({ stressColoring: v })),
}));
