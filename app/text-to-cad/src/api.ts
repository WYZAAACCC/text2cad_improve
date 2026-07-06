/**
 * API 服务层 — 对接 Text-to-CAD 后端
 *
 * 后端: server/main.py (FastAPI, port 8080)
 * 开发代理由 vite.config.ts 处理: /api/* -> localhost:8080
 */
import axios from 'axios';
import type {
  GenerationTask,
  DatasetEntry,
  DatasetEntryData,
} from './types';

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5 min — generation can be slow
  headers: { 'Content-Type': 'application/json' },
});

/**
 * POST /api/generate
 * 提交文本生成请求，返回 taskId 用于轮询
 */
export async function generateModel(text: string, sessionId: string, spatialGraphKey?: string, forceRoute?: string): Promise<string> {
  const { data } = await apiClient.post('/generate', { text, sessionId, spatialGraphKey, forceRoute });
  return data.taskId;
}

/**
 * GET /api/generate/{taskId}
 * 轮询任务状态直到 completed 或 failed
 */
export async function pollTaskStatus(taskId: string): Promise<GenerationTask> {
  const { data } = await apiClient.get(`/generate/${taskId}`);
  return {
    taskId: data.taskId,
    status: data.status,
    progress: data.progress,
    result: data.result ? {
      modelId: data.result.taskId || data.taskId,
      geometryType: 'step',
      parameters: data.result.parameters || {},
      stlUrl: data.result.stlFileUrl,
      stepUrl: data.result.stepFileUrl,
      stepFileSize: data.result.stepFileSize,
      metadataUrl: data.result.metadataUrl,
      ok: data.result.ok,
      failures: data.result.failures,
    } : undefined,
    error: data.error,
  };
}

/**
 * GET /api/dataset/list
 * 获取数据集列表
 */
export async function getDatasetList(): Promise<DatasetEntry[]> {
  const { data } = await apiClient.get('/dataset/list');
  if (!Array.isArray(data)) return [];
  return data.map((e: Record<string, unknown>) => ({
    id: e.id as string,
    name: e.name as string,
    thumbnailUrl: (e.thumbnailUrl as string) || '',
    tags: (e.tags as string[]) || [],
    createdAt: (e.createdAt as number) || 0,
    data: (e.data as DatasetEntryData) || {},
  }));
}

/**
 * POST /api/dataset/entry
 * 添加新数据集条目
 */
export async function addDatasetEntryApi(
  entry: Omit<DatasetEntry, 'id' | 'createdAt'> & { taskId?: string; data?: Record<string, unknown> }
): Promise<DatasetEntry> {
  const { data } = await apiClient.post('/dataset/entry', {
    name: entry.name,
    tags: entry.tags,
    taskId: (entry as { taskId?: string }).taskId,
    data: (entry as { data?: Record<string, unknown> }).data,
  });
  return {
    id: data.id,
    name: data.name,
    thumbnailUrl: data.thumbnailUrl || '',
    tags: data.tags || [],
    createdAt: data.createdAt || Date.now(),
    data: data.data || {},
  };
}

/**
 * GET /api/dataset/entry/{id}
 * 获取数据集条目详情
 */
export async function getDatasetEntryDetail(id: string): Promise<DatasetEntryData> {
  const { data } = await apiClient.get(`/dataset/entry/${id}`);
  return {
    userInput: data.userInput || '',
    featureGraph: data.featureGraph || { nodes: [], edges: [] },
    gcadDocument: data.gcadDocument || '',
    cadQueryCode: data.cadQueryCode || '',
    stepFileUrl: data.stepFileUrl || '',
    stepFileSize: data.stepFileSize || 'N/A',
    stlFileUrl: data.stlFileUrl || '',
    solveResult: data.solveResult || {},
    metadata: data.metadata || {},
    canonicalData: data,
  };
}

/**
 * DELETE /api/dataset/entry/{id}
 * 删除数据集条目
 */
export async function deleteDatasetEntryApi(id: string): Promise<void> {
  await apiClient.delete(`/dataset/entry/${id}`);
}

/**
 * POST /api/spatial/start
 * Run spatial frontend, returns questions if clarification needed
 */
export async function startSpatial(text: string, mode: string = 'guided'): Promise<{
  needsClarification: boolean;
  sessionId?: string;
  questions?: import('./components/SpatialModal').SpatialQuestion[];
  componentCount?: number;
  finalStatus?: string;
  constraintCount?: number;
  assumptions?: string[];
}> {
  const { data } = await apiClient.post('/spatial/start', { text, mode });
  return data;
}

/**
 * POST /api/spatial/continue
 * Submit user answers and continue spatial pipeline
 */
export async function continueSpatial(
  sessionId: string,
  answers: import('./components/SpatialModal').SpatialAnswer[]
): Promise<{
  needsClarification: boolean;
  sessionId?: string;
  questions?: import('./components/SpatialModal').SpatialQuestion[];
  finalStatus?: string;
  constraintCount?: number;
  assumptions?: string[];
}> {
  const { data } = await apiClient.post('/spatial/continue', { session_id: sessionId, answers });
  return data;
}

export { apiClient };
