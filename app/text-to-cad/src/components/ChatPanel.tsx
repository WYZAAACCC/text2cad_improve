/**
 * 左侧对话历史区组件
 * 展示用户消息、系统回复、模型卡片
 * 支持折叠、清空对话、复制文本、重新生成
 */
import { useState, useRef, useEffect } from 'react';
import {
  MessageSquare,
  Plus,
  Copy,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Box,
  Cpu,
  Settings,
  Download,
} from 'lucide-react';
import { useStore } from '../store';
import { setForceRoute } from '../App';
import type { ChatMessage } from '../types';

/** 生成进度条组件 */
function GenerationProgress() {
  const { generationProgress } = useStore();
  const stageLabels: Record<number, string> = {
    10: '启动中', 20: 'L1 路由分析', 35: 'L2 创作中', 45: 'L2 创作中',
    55: '校验中', 65: '校验中', 75: '几何生成', 85: 'STEP 导出', 100: '完成',
  };
  let stage = '处理中';
  for (const [k, v] of Object.entries(stageLabels)) {
    if (generationProgress <= Number(k)) { stage = v; break; }
  }
  if (generationProgress >= 100) stage = '完成';
  return (
    <div className="mb-4 bg-bg-tertiary rounded-xl p-4 border border-border">
      <div className="flex items-center gap-2 mb-2">
        <Loader2 className="w-4 h-4 animate-spin text-accent" />
        <span className="text-sm text-text-primary">AI 正在生成模型</span>
        <span className="text-xs text-text-muted ml-auto">{stage}</span>
      </div>
      <div className="w-full bg-bg-primary rounded-full h-2 overflow-hidden">
        <div className="h-full bg-accent rounded-full transition-all duration-500"
          style={{ width: `${Math.max(5, generationProgress)}%` }} />
      </div>
    </div>
  );
}

/** 格式化时间 */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
}

/** 复制文本到剪贴板 */
async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 降级方案
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }
}

/** 单条消息组件 */
function MessageItem({
  message,
  onRegenerate,
}: {
  message: ChatMessage;
  onRegenerate?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const handleCopy = async () => {
    await copyToClipboard(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[85%] ${isUser ? 'order-2' : 'order-1'}`}>
        {/* 消息气泡 */}
        <div
          className={`rounded-2xl px-4 py-3 ${
            isUser
              ? 'bg-accent text-white rounded-br-md'
              : 'bg-bg-tertiary text-text-primary rounded-bl-md'
          }`}
        >
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
        </div>

        {/* 模型卡片（仅系统消息） */}
        {!isUser && message.modelCard && (
          <div className="mt-2 bg-bg-secondary border border-border rounded-xl p-3">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #1a3a5c, #2a1a3a)' }}>
                <Box className="w-6 h-6 text-accent" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">
                  {message.modelCard.modelName}
                </p>
                <p className="text-xs text-text-muted mt-0.5">
                  {message.modelCard.stepFileSize || 'CAD Model'}
                </p>
              </div>
            </div>
            {/* 下载按钮 */}
            <div className="flex items-center gap-2 mt-2.5 pt-2.5 border-t border-border/50">
              {message.modelCard.stepFileUrl && (
                <a
                  href={message.modelCard.stepFileUrl}
                  download={message.modelCard.modelName.replace(/\s.*$/, '') + '.step'}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/10 hover:bg-accent/20 text-accent text-xs transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  STEP
                </a>
              )}
              {message.modelCard.stlFileUrl && (
                <a
                  href={message.modelCard.stlFileUrl}
                  download={message.modelCard.modelName.replace(/\s.*$/, '') + '.stl'}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/10 hover:bg-accent/20 text-accent text-xs transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  STL
                </a>
              )}
            </div>
          </div>
        )}

        {/* 操作栏 */}
        <div
          className={`flex items-center gap-2 mt-1.5 ${
            isUser ? 'justify-end' : 'justify-start'
          }`}
        >
          <span className="text-xs text-text-muted">{formatTime(message.timestamp)}</span>

          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-xs text-text-muted hover:text-text-secondary transition-colors px-1.5 py-0.5 rounded hover:bg-bg-hover"
            title="复制文本"
          >
            <Copy className="w-3 h-3" />
            {copied ? '已复制' : '复制'}
          </button>

          {!isUser && onRegenerate && (
            <button
              onClick={onRegenerate}
              className="flex items-center gap-1 text-xs text-text-muted hover:text-text-secondary transition-colors px-1.5 py-0.5 rounded hover:bg-bg-hover"
              title="重新生成"
            >
              <RefreshCw className="w-3 h-3" />
              重新生成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** 对话历史面板 */
export default function ChatPanel() {
  const {
    messages,
    isGenerating,
    leftPanelCollapsed,
    setLeftPanelCollapsed,
    clearMessages,
    addMessage,
  } = useStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [inputText, setInputText] = useState('');
  const [routeMode, setRouteMode] = useState<'auto' | 'generative' | 'primitive'>('auto');

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isGenerating]);

  // 发送消息
  const handleSend = async () => {
    if (!inputText.trim() || isGenerating) return;

    const text = inputText.trim();
    setInputText('');

    // 设置路由模式
    const routeMap: Record<string, string | undefined> = {
      'auto': undefined,
      'generative': 'generative_cad_ir',
      'primitive': 'deterministic_primitive',
    };
    setForceRoute(routeMap[routeMode]);

    // 添加用户消息
    addMessage({
      role: 'user',
      content: text,
    });

    // 触发全局生成事件（由 App.tsx 处理）
    window.dispatchEvent(new CustomEvent('cad:generate', { detail: text }));
  };

  // 重新生成最后一条系统消息
  const handleRegenerate = () => {
    const lastUserMessage = [...messages].reverse().find((m) => m.role === 'user');
    if (lastUserMessage) {
      window.dispatchEvent(
        new CustomEvent('cad:generate', { detail: lastUserMessage.content })
      );
    }
  };

  // 新建对话
  const handleNewChat = () => {
    clearMessages();
    addMessage({
      role: 'system',
      content: '新对话已创建。请输入自然语言描述来生成 3D 模型。',
    });
  };

  if (leftPanelCollapsed) {
    return (
      <div className="w-10 bg-bg-secondary border-r border-border flex flex-col items-center py-3 flex-shrink-0">
        <button
          onClick={() => setLeftPanelCollapsed(false)}
          className="p-2 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors"
          title="展开对话面板"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
        <div className="mt-4">
          <MessageSquare className="w-5 h-5 text-text-muted" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-80 bg-bg-secondary border-r border-border flex flex-col flex-shrink-0">
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-accent" />
          <span className="text-sm font-medium text-text-primary">对话历史</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNewChat}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors"
            title="新建对话"
          >
            <Plus className="w-4 h-4" />
          </button>
          <button
            onClick={() => setLeftPanelCollapsed(true)}
            className="p-1.5 rounded-lg hover:bg-bg-hover text-text-secondary transition-colors"
            title="折叠面板"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-text-muted">
            <MessageSquare className="w-10 h-10 mb-2 opacity-50" />
            <p className="text-sm">暂无对话记录</p>
          </div>
        ) : (
          messages.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              onRegenerate={
                message.role === 'system' ? handleRegenerate : undefined
              }
            />
          ))
        )}

        {/* 生成中状态 */}
        {isGenerating && (
          <GenerationProgress />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 底部输入区 */}
      <div className="px-4 py-3 border-t border-border">
        {/* 路由模式切换 */}
        <div className="flex items-center gap-1 mb-2">
          <button
            onClick={() => setRouteMode('auto')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
              routeMode === 'auto' ? 'bg-accent/20 text-accent' : 'text-text-muted hover:text-text-secondary'
            }`}
            title="自动选择路线（默认）"
          ><Settings className="w-3 h-3" />自动</button>
          <button
            onClick={() => setRouteMode('generative')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
              routeMode === 'generative' ? 'bg-accent/20 text-accent' : 'text-text-muted hover:text-text-secondary'
            }`}
            title="强制使用生成式 CAD IR 路线"
          ><Cpu className="w-3 h-3" />生成式</button>
          <button
            onClick={() => setRouteMode('primitive')}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
              routeMode === 'primitive' ? 'bg-accent/20 text-accent' : 'text-text-muted hover:text-text-secondary'
            }`}
            title="使用确定性 Primitive 路线"
          ><Box className="w-3 h-3" />Primitive</button>
        </div>
        <div className="flex items-end gap-2">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="描述你想要的 3D 模型..."
            className="flex-1 bg-bg-tertiary border border-border rounded-xl px-3 py-2.5 text-sm text-text-primary placeholder-text-muted resize-none outline-none focus:border-accent transition-colors"
            rows={2}
          />
          <button
            onClick={handleSend}
            disabled={!inputText.trim() || isGenerating}
            className="px-4 py-2.5 bg-accent text-white rounded-xl text-sm font-medium hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
