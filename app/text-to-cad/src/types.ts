/**
 * 类型定义 — 对齐后端 server/main.py 和 generative_cad 数据格式
 */

/** 几何体类型 (procedural primitives) */
export type GeometryType = 'box' | 'sphere' | 'cylinder' | 'cone' | 'torus';

/** 程序化模型参数 */
export interface ModelParameters {
  width?: number;
  height?: number;
  depth?: number;
  radius?: number;
  tube?: number;
  radialSegments?: number;
  heightSegments?: number;
  tubularSegments?: number;
  length?: number;
}

/** 场景中的模型对象 */
export interface SceneModel {
  id: string;
  name: string;
  type: 'box' | 'sphere' | 'cylinder' | 'cone' | 'torus' | 'step';
  visible: boolean;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  parameters: Record<string, unknown>;
  color: string;
  /** STL file URL for loading real CAD geometry */
  stlUrl?: string | null;
}

/** 对话消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'system';
  content: string;
  timestamp: number;
  modelCard?: ModelCard;
}

/** 模型卡片（显示在对话中） */
export interface ModelCard {
  modelId: string;
  modelName: string;
  thumbnailUrl: string;
  stepFileUrl?: string;
  stlFileUrl?: string;
  stepFileSize?: string;
  ok?: boolean;
}

/** 数据集条目 */
export interface DatasetEntry {
  id: string;
  name: string;
  thumbnailUrl: string;
  tags: string[];
  createdAt: number;
  data: DatasetEntryData;
}

/** 数据集条目的详细数据 */
export interface DatasetEntryData {
  userInput: string;
  featureGraph: FeatureGraph;
  gcadDocument: string;
  cadQueryCode: string;
  stepFileUrl: string;
  stepFileSize: string;
  stlFileUrl?: string;
  solveResult: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  canonicalData?: Record<string, unknown>;
}

/** 特征图 */
export interface FeatureGraph {
  nodes: FeatureNode[];
  edges: FeatureEdge[];
}

/** 特征节点 */
export interface FeatureNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
}

/** 特征边 */
export interface FeatureEdge {
  from: string;
  to: string;
  relation: string;
}

/** 生成任务状态 */
export type GenerationStatus = 'pending' | 'processing' | 'completed' | 'failed';

/** 生成任务 */
export interface GenerationTask {
  taskId: string;
  status: GenerationStatus;
  progress: number;
  result?: {
    modelId: string;
    geometryType: string;
    parameters: Record<string, unknown>;
    stlUrl?: string | null;
    stepUrl?: string;
    stepFileSize?: string;
    metadataUrl?: string;
    ok?: boolean;
    failures?: unknown[];
  };
  error?: string;
}

/** FEA Analysis Types */
export interface FeaTemplateParam {
  type: string;
  required: boolean;
  default: unknown;
  min?: number;
  max?: number;
  description: string;
}

export interface FeaTemplateSchema {
  name: string;
  analysis_type: string;
  units: string;
  parameters: Record<string, FeaTemplateParam>;
  metrics: string[];
}

export interface FeaRegionDef {
  region_id: string;
  region_type: 'cylindrical' | 'planar' | 'conical' | 'axis' | 'plane';
  label_cn: string;
  label_en: string;
  r_mm?: number;
  r_tolerance?: number;
  z_mm?: number;
  r_min?: number;
  r_max?: number;
  z_min?: number;
  z_max?: number;
  origin?: number[];
  direction?: number[];
  normal?: number[];
  color: string;
  highlight_opacity: number;
}

export interface FeaResult {
  task_id: string;
  ok: boolean;
  template_name: string;
  elapsed_s: number;
  message: string;
  metrics: Record<string, number>;
  warnings: string[];
  files_created: string[];
  log_path: string | null;
  error: string | null;
  stress_field?: StressPoint[];
}

export interface StressPoint {
  r_mm: number;
  z_mm: number;
  sx_mpa: number;
  sy_mpa: number;
  sz_mpa: number;
  sxy_mpa: number;
  seqv_mpa: number;
}

export interface FeaQuestion {
  question_id: string;
  category: string;
  question_text: string;
  why_it_matters: string;
  param_key: string;
  param_type: string;
  options: FeaQuestionOption[];
  default_value: unknown;
  allow_custom: boolean;
  unit: string;
}

export interface FeaQuestionOption {
  option_id: string;
  label: string;
  description: string;
  recommended: boolean;
}

export interface FeaAnswer {
  question_id: string;
  mode: 'option' | 'custom' | 'auto';
  selected_option_id?: string;
  custom_value?: unknown;
}

export interface FeaTask {
  task_id: string;
  status: string;
  progress: number;
  result: FeaResult | null;
  error: string | null;
}

export interface FeaHistoryEntry {
  id: string;
  timestamp: number;
  template_name: string;
  parameters: Record<string, unknown>;
  result: FeaResult;
}
