/**
 * 运行过程面板：实时展示模型思考链与系统各阶段运行细节。
 */
import { useState } from 'react';
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Loader2,
} from 'lucide-react';
import { useStore } from '../store';
import type { TraceEvent } from '../types';

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
}

function statusIcon(status: string) {
  if (status === 'completed') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
  if (status === 'failed') return <CircleAlert className="w-3.5 h-3.5 text-danger" />;
  return <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />;
}

function DataBlock({ data }: { data: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const text = JSON.stringify(data, null, 2);
  const preview = text.length > 180 ? `${text.slice(0, 180)}...` : text;

  return (
    <div className="mt-2 rounded-lg bg-bg-primary border border-border overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-2.5 py-1.5 text-[10px] text-text-muted hover:text-text-secondary transition-colors"
      >
        <span>细节数据</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <pre className="px-2.5 pb-2.5 text-[10px] leading-relaxed text-text-secondary whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
          {text}
        </pre>
      )}
      {!open && (
        <p className="px-2.5 pb-2 text-[10px] text-text-muted whitespace-pre-wrap break-words">{preview}</p>
      )}
    </div>
  );
}

function TraceItem({ event, index, total }: { event: TraceEvent; index: number; total: number }) {
  const isLast = index === total - 1;
  const reasoning = (event.data as { reasoning?: string } | undefined)?.reasoning;
  return (
    <div className="relative pl-5 pb-4">
      {!isLast && <div className="absolute left-[5px] top-3 bottom-0 w-px bg-border" />}
      <div className="absolute left-0 top-1.5 w-2.5 h-2.5 rounded-full bg-bg-tertiary border border-border flex items-center justify-center">
        <div className="w-1.5 h-1.5 rounded-full bg-accent/80" />
      </div>
      <div className="flex items-center gap-1.5">
        {statusIcon(event.status)}
        <span className="text-xs font-medium text-text-primary">{event.title}</span>
        <span className="text-[10px] text-text-muted ml-auto">{formatTime(event.ts)}</span>
      </div>
      {reasoning ? (
        <p className="text-[11px] text-text-secondary mt-1 leading-relaxed whitespace-pre-wrap break-words max-h-56 overflow-y-auto">
          {reasoning}
        </p>
      ) : (
        <>
          <p className="text-[11px] text-text-secondary mt-1 leading-relaxed">{event.message}</p>
          {event.data && <DataBlock data={event.data} />}
        </>
      )}
    </div>
  );
}

export default function RunTracePanel() {
  const { generationTrace, generationProgress, generationStage } = useStore();
  const [autoScroll, setAutoScroll] = useState(true);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-text-primary">运行过程</h3>
          <Activity className="w-4 h-4 text-accent" />
        </div>
        <div className="flex items-center gap-2 mt-2">
          <div className="flex-1 bg-bg-tertiary rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full bg-accent rounded-full transition-all duration-500"
              style={{ width: `${Math.max(4, generationProgress)}%` }}
            />
          </div>
          <span className="text-[10px] text-text-muted">{Math.round(generationProgress)}%</span>
        </div>
        {generationStage && (
          <p className="text-[11px] text-text-secondary mt-1.5">{generationStage}</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {generationTrace.length === 0 ? (
          <div className="text-center py-10 text-text-muted">
            <Activity className="w-7 h-7 mx-auto mb-2 opacity-40" />
            <p className="text-xs">尚无运行记录</p>
            <p className="text-[10px] mt-1">提交生成任务后，这里会实时展示思考链与系统细节</p>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-3">
              <button
                onClick={() => setAutoScroll(!autoScroll)}
                className="flex items-center gap-1 px-2 py-1 rounded bg-bg-tertiary text-[10px] text-text-secondary hover:text-text-primary transition-colors"
              >
                <ChevronDown className={`w-3 h-3 transition-transform ${autoScroll ? 'rotate-180' : ''}`} />
                {autoScroll ? '自动滚动' : '手动滚动'}
              </button>
              <span className="text-[10px] text-text-muted">{generationTrace.length} 条事件</span>
            </div>
            <div ref={(el) => {
              if (el && autoScroll) el.scrollTop = el.scrollHeight;
            }}>
              {generationTrace.map((event, i) => (
                <TraceItem key={`${event.ts}-${i}`} event={event} index={i} total={generationTrace.length} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
