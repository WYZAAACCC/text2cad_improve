/**
 * 空间问题交互弹窗 — LLM 向人提问不确定的几何布局
 *
 * 每个问题包含：
 * - questionText: 问题描述
 * - whyItMatters: 为什么重要
 * - options[]: 预定义选择项（含 geometricConsequence）
 * - allowCustom: 是否允许自定义输入（"其他"按钮）
 * - allowAuto: 是否允许委托系统自动决策
 */
import { useState } from 'react';
import { HelpCircle, AlertTriangle, Check, ChevronRight, MessageSquare, X } from 'lucide-react';
const XIcon = X;
import * as Dialog from '@radix-ui/react-dialog';

export interface SpatialOption {
  optionId: string;
  label: string;
  description: string;
  recommended: boolean;
  geometricConsequence: string;
}

export interface SpatialQuestion {
  questionId: string;
  questionText: string;
  whyItMatters: string;
  type: string;
  options: SpatialOption[];
  allowCustom: boolean;
  allowAuto: boolean;
  allowCustomLabel?: string;
  allowAutoLabel?: string;
}

export interface SpatialAnswer {
  questionId: string;
  mode: 'option' | 'custom' | 'auto';
  selectedOptionId?: string;
  customText?: string;
  autoLevel?: string;
}

interface Props {
  questions: SpatialQuestion[];
  sessionId: string;
  componentCount: number;
  onSubmit: (answers: SpatialAnswer[]) => void;
  onCancel: () => void;
}

/** 单个问题卡片 */
function QuestionCard({
  question,
  answer,
  onChange,
}: {
  question: SpatialQuestion;
  answer: SpatialAnswer | null;
  onChange: (a: SpatialAnswer) => void;
}) {
  const [customOpen, setCustomOpen] = useState(false);
  const [customText, setCustomText] = useState('');

  const selectedId = answer?.selectedOptionId;
  const isCustom = answer?.mode === 'custom';
  const isAuto = answer?.mode === 'auto';

  const handleOption = (opt: SpatialOption) => {
    setCustomOpen(false);
    onChange({ questionId: question.questionId, mode: 'option', selectedOptionId: opt.optionId });
  };

  const handleCustom = () => {
    setCustomOpen(true);
    onChange({ questionId: question.questionId, mode: 'custom', customText });
  };

  const handleCustomSubmit = () => {
    onChange({ questionId: question.questionId, mode: 'custom', customText: customText || '自定义' });
  };

  const handleAuto = () => {
    setCustomOpen(false);
    onChange({ questionId: question.questionId, mode: 'auto', autoLevel: 'auto_mechanical' });
  };

  return (
    <div className="bg-bg-tertiary border border-border rounded-xl p-4">
      {/* 问题标题 */}
      <div className="flex items-start gap-2 mb-3">
        <HelpCircle className="w-5 h-5 text-accent mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium text-text-primary">{question.questionText}</p>
          <p className="text-xs text-text-muted mt-1 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            {question.whyItMatters}
          </p>
        </div>
      </div>

      {/* 选项列表 */}
      <div className="space-y-2 ml-7">
        {question.options.map((opt) => (
          <button
            key={opt.optionId}
            onClick={() => handleOption(opt)}
            className={`w-full text-left p-3 rounded-lg border transition-all ${
              selectedId === opt.optionId
                ? 'border-accent bg-accent/10'
                : 'border-border hover:border-accent/50 hover:bg-bg-hover'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-primary">
                {opt.label}
              </span>
              {selectedId === opt.optionId && <Check className="w-4 h-4 text-accent" />}
            </div>
            <p className="text-xs text-text-muted mt-1">{opt.description}</p>
            {opt.geometricConsequence && (
              <p className="text-xs text-accent/70 mt-0.5">{opt.geometricConsequence}</p>
            )}
          </button>
        ))}

        {/* "其他" 自定义选项 */}
        {question.allowCustom && (
          <div>
            {!customOpen ? (
              <button
                onClick={handleCustom}
                className={`w-full text-left p-3 rounded-lg border transition-all ${
                  isCustom ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/50 hover:bg-bg-hover'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm text-text-primary">{question.allowCustomLabel || '其他 — 自定义输入'}</span>
                  <MessageSquare className="w-4 h-4 text-text-muted" />
                </div>
                <p className="text-xs text-text-muted mt-1">输入选项中没有的答案</p>
              </button>
            ) : (
              <div className="p-3 rounded-lg border border-accent bg-accent/5">
                <textarea
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  placeholder="输入你的答案..."
                  className="w-full bg-bg-tertiary border border-border rounded-lg p-2 text-sm text-text-primary placeholder-text-muted resize-none outline-none focus:border-accent"
                  rows={2}
                  autoFocus
                />
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={handleCustomSubmit}
                    className="px-3 py-1.5 bg-accent text-white rounded-lg text-xs font-medium"
                  >
                    提交
                  </button>
                  <button
                    onClick={() => setCustomOpen(false)}
                    className="px-3 py-1.5 bg-bg-tertiary border border-border rounded-lg text-xs text-text-secondary"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* "交给系统自动" 选项 */}
        {question.allowAuto && (
          <button
            onClick={handleAuto}
            className={`w-full text-left p-3 rounded-lg border transition-all ${
              isAuto ? 'border-accent bg-accent/10' : 'border-border hover:border-accent/50 hover:bg-bg-hover'
            }`}
          >
            <span className="text-sm text-text-muted">{question.allowAutoLabel || '自动 — 交给系统决定'}</span>
          </button>
        )}
      </div>
    </div>
  );
}

/** 主弹窗 */
export default function SpatialModal({ questions, sessionId, componentCount, onSubmit, onCancel }: Props) {
  const [answers, setAnswers] = useState<Map<string, SpatialAnswer>>(new Map());
  const [currentIdx, setCurrentIdx] = useState(0);

  const currentQ = questions[currentIdx];
  const allAnswered = questions.every((q) => answers.has(q.questionId));

  const handleAnswerChange = (a: SpatialAnswer) => {
    const next = new Map(answers);
    next.set(a.questionId, a);
    setAnswers(next);
  };

  const handleSubmit = () => {
    onSubmit(questions.map((q) => answers.get(q.questionId)!));
  };

  return (
    <Dialog.Root open modal>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50" />
        <Dialog.Content className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div className="bg-bg-secondary border border-border rounded-2xl w-full max-w-lg max-h-[85vh] flex flex-col shadow-2xl">
            {/* Header */}
            <div className="px-5 py-4 border-b border-border flex items-center justify-between flex-shrink-0">
              <div>
                <Dialog.Title className="text-base font-semibold text-text-primary">
                  空间位置确认
                </Dialog.Title>
                <p className="text-xs text-text-muted mt-0.5">
                  会话 {sessionId.slice(0, 8)} · {componentCount} 个组件
                </p>
              </div>
              <div className="flex items-center gap-2">
                <div className="text-xs text-text-muted bg-bg-tertiary px-2 py-1 rounded">
                  {currentIdx + 1}/{questions.length}
                </div>
                <Dialog.Close asChild>
                  <button onClick={onCancel} className="p-1 rounded hover:bg-bg-hover text-text-muted">
                    <XIcon />
                  </button>
                </Dialog.Close>
              </div>
            </div>

            {/* Question */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {currentQ && (
                <QuestionCard
                  question={currentQ}
                  answer={answers.get(currentQ.questionId) || null}
                  onChange={handleAnswerChange}
                />
              )}
            </div>

            {/* Footer with navigation */}
            <div className="px-5 py-3 border-t border-border flex items-center justify-between flex-shrink-0">
              <div className="flex gap-1">
                {questions.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setCurrentIdx(i)}
                    className={`w-2.5 h-2.5 rounded-full transition-all ${
                      i === currentIdx
                        ? 'bg-accent w-6'
                        : answers.has(questions[i].questionId)
                        ? 'bg-accent/50'
                        : 'bg-border'
                    }`}
                  />
                ))}
              </div>

              <div className="flex gap-2">
                {currentIdx > 0 && (
                  <button
                    onClick={() => setCurrentIdx((i) => i - 1)}
                    className="px-3 py-1.5 border border-border rounded-lg text-xs text-text-secondary hover:bg-bg-hover"
                  >
                    上一步
                  </button>
                )}
                {currentIdx < questions.length - 1 ? (
                  <button
                    onClick={() => setCurrentIdx((i) => i + 1)}
                    disabled={!answers.has(currentQ?.questionId)}
                    className="px-4 py-1.5 bg-accent text-white rounded-lg text-xs font-medium flex items-center gap-1 disabled:opacity-50"
                  >
                    下一步 <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={handleSubmit}
                    disabled={!allAnswered}
                    className="px-4 py-1.5 bg-accent text-white rounded-lg text-xs font-medium disabled:opacity-50"
                  >
                    提交 ({questions.filter((q) => answers.has(q.questionId)).length}/{questions.length})
                  </button>
                )}
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
