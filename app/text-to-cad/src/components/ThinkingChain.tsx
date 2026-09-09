/**
 * 滚动思考链：实时展示 Agent 推理文本流，并自动滚动到底部。
 */
import { useEffect, useRef } from 'react';
import { BrainCircuit, Loader2 } from 'lucide-react';
import { useStore } from '../store';
import type { TraceEvent } from '../types';

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`;
}

export default function ThinkingChain({ maxHeight = 'max-h-52' }: { maxHeight?: string }) {
  const { generationTrace, isGenerating } = useStore();
  const scrollRef = useRef<HTMLDivElement>(null);

  const chain = generationTrace.filter((e) => e.data?.reasoning) as Array<
    TraceEvent & { data: { reasoning: string; agent?: string; kind?: string } }
  >;
  const chainKey = chain.map((e) => `${e.ts}-${String(e.data.reasoning).length}`).join('|');

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chainKey]);

  return (
    <div className="rounded-xl bg-bg-primary border border-border overflow-hidden">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border">
        <BrainCircuit className="w-3.5 h-3.5 text-accent" />
        <span className="text-[11px] font-medium text-text-primary">思考链</span>
        {isGenerating && <Loader2 className="w-3 h-3 animate-spin text-accent ml-auto" />}
        <span className="text-[10px] text-text-muted ml-auto">{chain.length} 条推理</span>
      </div>

      <div ref={scrollRef} className={`${maxHeight} overflow-y-auto px-3 py-2 space-y-2.5`}>
        {chain.length === 0 ? (
          <p className="text-[11px] text-text-muted py-2">
            {isGenerating ? 'Agent 正在推理，思考链即将滚动...' : '生成任务后，这里会实时滚动 Agent 思考链'}
          </p>
        ) : (
          chain.map((event, i) => (
            <div key={`${event.ts}-${i}`} className="thinking-entry">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent flex-shrink-0" />
                <span className="text-[10px] font-medium text-accent">
                  {event.data.agent || event.title}
                </span>
                <span className="text-[9px] text-text-muted ml-auto">{formatTime(event.ts)}</span>
              </div>
              <p className="text-[11px] leading-relaxed text-text-secondary whitespace-pre-wrap break-words">
                {event.data.reasoning}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
