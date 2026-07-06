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
