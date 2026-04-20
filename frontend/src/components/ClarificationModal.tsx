import React from 'react';
import { LoaderCircle, Sparkles } from 'lucide-react';
import {
  ClarificationAnswer,
  ClarificationHistoryRound,
  ClarificationQuestion,
  ClarificationState,
} from '../types';
import { Button } from './ui';

const CUSTOM_LABEL = '其它（自填）';

interface ClarificationModalProps {
  state: ClarificationState;
  onSubmit: (runId: string, answers: ClarificationAnswer[]) => Promise<void>;
}

interface Selection {
  label: string;
  customText: string;
}

export const ClarificationModal: React.FC<ClarificationModalProps> = ({ state, onSubmit }) => {
  const [selections, setSelections] = React.useState<Record<string, Selection>>({});
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    setSelections({});
    setError('');
  }, [state.requestArtifactId]);

  const selectionKey = (idx: number, header: string) => `${idx}#${header}`;

  const chooseOption = (key: string, label: string) => {
    setSelections((prev) => ({
      ...prev,
      [key]: { label, customText: prev[key]?.customText ?? '' },
    }));
  };

  const updateCustomText = (key: string, text: string) => {
    setSelections((prev) => ({
      ...prev,
      [key]: { label: CUSTOM_LABEL, customText: text },
    }));
  };

  const allAnswered = state.questions.every((q, idx) => {
    const sel = selections[selectionKey(idx, q.header)];
    if (!sel || !sel.label) return false;
    if (sel.label === CUSTOM_LABEL) return sel.customText.trim().length > 0;
    return true;
  });

  const handleSubmit = async () => {
    if (!allAnswered || submitting) return;
    const answers: ClarificationAnswer[] = state.questions.map((q, idx) => {
      const sel = selections[selectionKey(idx, q.header)]!;
      if (sel.label === CUSTOM_LABEL) {
        return {
          question_header: q.header,
          label: CUSTOM_LABEL,
          custom_text: sel.customText.trim(),
        };
      }
      return { question_header: q.header, label: sel.label };
    });
    setSubmitting(true);
    setError('');
    try {
      await onSubmit(state.runId, answers);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 px-4 py-6 backdrop-blur-sm">
      <div
        className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[var(--shadow-modal)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-6 pt-6 pb-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-600">
                澄清研究意图 · 第 {state.roundNum} 轮
              </p>
              <h3 className="mt-1 text-base font-semibold text-slate-900">
                请选择与你目标最接近的选项
              </h3>
            </div>
          </div>
          <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-[11px] font-medium text-indigo-700">
            CLARIFY
          </span>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {state.history.length > 0 ? <HistoryTimeline rounds={state.history} /> : null}

          <div className="flex flex-col gap-5">
            {state.questions.map((question, idx) => {
              const key = selectionKey(idx, question.header);
              return (
                <QuestionCard
                  key={key}
                  question={question}
                  selection={selections[key]}
                  autoFocusFirstOption={idx === 0}
                  onChoose={(label) => chooseOption(key, label)}
                  onCustomText={(text) => updateCustomText(key, text)}
                />
              );
            })}
          </div>
        </div>

        <div className="border-t border-slate-100 px-6 py-4">
          {error ? (
            <p className="mb-3 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p>
          ) : null}
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-slate-400">
              每个问题选择一个选项；选择"{CUSTOM_LABEL}"后请填写具体内容。
            </p>
            <Button
              onClick={() => void handleSubmit()}
              disabled={!allAnswered || submitting}
              className="rounded-full px-5"
            >
              {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              {submitting ? '提交中…' : '提交回答'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

const HistoryTimeline: React.FC<{ rounds: ClarificationHistoryRound[] }> = ({ rounds }) => (
  <div className="mb-5 rounded-[20px] border border-slate-100 bg-slate-50 px-4 py-3">
    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">已回答</p>
    <div className="flex flex-col gap-3">
      {rounds.map((round) => (
        <div key={round.round_num} className="rounded-2xl border border-slate-200 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            第 {round.round_num} 轮
          </p>
          <ul className="mt-1 space-y-1 text-xs leading-5 text-slate-600">
            {round.answers.map((ans, idx) => (
              <li key={`${ans.question_header}-${idx}`} className="flex flex-col">
                <span className="font-medium text-slate-700">{ans.question_header}</span>
                <span className="text-slate-500">
                  {ans.label}
                  {ans.custom_text ? ` — ${ans.custom_text}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  </div>
);

interface QuestionCardProps {
  question: ClarificationQuestion;
  selection: Selection | undefined;
  autoFocusFirstOption?: boolean;
  onChoose: (label: string) => void;
  onCustomText: (text: string) => void;
}

const QuestionCard: React.FC<QuestionCardProps> = ({
  question,
  selection,
  autoFocusFirstOption,
  onChoose,
  onCustomText,
}) => {
  const selectedLabel = selection?.label ?? '';
  const isCustom = selectedLabel === CUSTOM_LABEL;

  return (
    <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-500">
        {question.header}
      </p>
      <p className="mt-1 text-sm leading-6 text-slate-800">{question.question}</p>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {question.options.map((option, optIdx) => {
          const selected = selectedLabel === option.label;
          return (
            <button
              key={option.label}
              type="button"
              autoFocus={autoFocusFirstOption && optIdx === 0}
              onClick={() => onChoose(option.label)}
              className={`flex flex-col rounded-2xl border px-3 py-2 text-left transition ${
                selected
                  ? 'border-indigo-400 bg-indigo-50 text-indigo-900 shadow-sm'
                  : 'border-slate-200 bg-white text-slate-700 hover:border-indigo-300 hover:bg-indigo-50/40'
              }`}
            >
              <span className="text-sm font-medium">{option.label}</span>
              {option.description ? (
                <span className="mt-0.5 text-xs leading-5 text-slate-500">{option.description}</span>
              ) : null}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => onChoose(CUSTOM_LABEL)}
          className={`flex flex-col rounded-2xl border px-3 py-2 text-left transition ${
            isCustom
              ? 'border-indigo-400 bg-indigo-50 text-indigo-900 shadow-sm'
              : 'border-dashed border-slate-300 bg-white text-slate-600 hover:border-indigo-300 hover:bg-indigo-50/40'
          }`}
        >
          <span className="text-sm font-medium">{CUSTOM_LABEL}</span>
          <span className="mt-0.5 text-xs leading-5 text-slate-500">
            选择后在下方文本框填写你的具体意图
          </span>
        </button>
      </div>
      {isCustom ? (
        <textarea
          value={selection?.customText ?? ''}
          onChange={(e) => onCustomText(e.target.value)}
          placeholder="请描述你的具体目标或偏好…"
          className="mt-3 min-h-[72px] w-full resize-none rounded-[16px] border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
        />
      ) : null}
    </div>
  );
};
