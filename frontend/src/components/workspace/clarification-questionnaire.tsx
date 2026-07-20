import { MessageSquareTextIcon, SparklesIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const QUESTIONNAIRE_TYPE = "clarification_questionnaire";
const OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export interface ClarificationQuestionnaireOption {
  description?: string;
  label: string;
  value: string;
}

export interface ClarificationQuestionnaireQuestion {
  id: string;
  options: ClarificationQuestionnaireOption[];
  title: string;
}

export interface ClarificationQuestionnairePayload {
  directSubmitLabel?: string;
  prompt?: string;
  questions: ClarificationQuestionnaireQuestion[];
  submitLabel?: string;
  title?: string;
}

interface ExtractedClarificationQuestionnaire {
  payload: ClarificationQuestionnairePayload;
  visibleContent: string;
}

interface QuestionnaireCandidate {
  block: string;
  json: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function optionFromUnknown(
  value: unknown,
  index: number,
): ClarificationQuestionnaireOption | null {
  if (typeof value === "string" && value.trim()) {
    return {
      value: `option_${index + 1}`,
      label: value.trim(),
    };
  }
  if (!isRecord(value)) return null;
  const label =
    stringValue(value.label) ??
    stringValue(value.title) ??
    stringValue(value.text) ??
    stringValue(value.value);
  if (!label) return null;
  return {
    value: stringValue(value.value) ?? `option_${index + 1}`,
    label,
    description: stringValue(value.description) ?? stringValue(value.detail),
  };
}

function questionFromUnknown(
  value: unknown,
  index: number,
): ClarificationQuestionnaireQuestion | null {
  if (!isRecord(value)) return null;
  const title =
    stringValue(value.title) ??
    stringValue(value.question) ??
    stringValue(value.label);
  if (!title || !Array.isArray(value.options)) return null;

  const options = value.options
    .map(optionFromUnknown)
    .filter((option): option is ClarificationQuestionnaireOption =>
      Boolean(option),
    )
    .slice(0, 8);
  if (options.length < 2) return null;

  return {
    id: stringValue(value.id) ?? `question_${index + 1}`,
    title,
    options,
  };
}

function normalizePayload(
  value: unknown,
): ClarificationQuestionnairePayload | null {
  if (!isRecord(value)) return null;
  const source = isRecord(value.questionnaire) ? value.questionnaire : value;
  const type = stringValue(source.type) ?? stringValue(value.type);
  const isAskUserQuestionResult =
    !type &&
    stringValue(source.question) &&
    Array.isArray(source.options) &&
    ("allow_other" in source ||
      "allowOther" in source ||
      "yield_turn" in source ||
      "posted" in source ||
      "ok" in source);
  if (type !== QUESTIONNAIRE_TYPE && !isAskUserQuestionResult) return null;

  const rawQuestions = Array.isArray(source.questions)
    ? source.questions
    : isAskUserQuestionResult
      ? [
          {
            id: "answer",
            title: source.question,
            options: source.options,
          },
        ]
      : null;
  if (!rawQuestions) return null;

  const questions = rawQuestions
    .map(questionFromUnknown)
    .filter((question): question is ClarificationQuestionnaireQuestion =>
      Boolean(question),
    )
    .slice(0, 10);
  if (questions.length === 0) return null;

  return {
    title: stringValue(source.title),
    prompt: stringValue(source.prompt) ?? stringValue(source.context),
    questions,
    submitLabel:
      stringValue(source.submitLabel) ?? stringValue(source.submit_label),
    directSubmitLabel:
      stringValue(source.directSubmitLabel) ??
      stringValue(source.direct_submit_label),
  };
}

function parsePayload(json: string): ClarificationQuestionnairePayload | null {
  try {
    return normalizePayload(JSON.parse(json));
  } catch {
    return null;
  }
}

function collectCandidates(content: string): QuestionnaireCandidate[] {
  const candidates: QuestionnaireCandidate[] = [];
  const tagPattern =
    /<clarification_questionnaire\b[^>]*>\s*([\s\S]*?)\s*<\/clarification_questionnaire>/gi;
  for (const match of content.matchAll(tagPattern)) {
    const block = match[0];
    const json = match[1];
    if (block && json) candidates.push({ block, json });
  }

  const fencePattern = /```(?:json)?\s*([\s\S]*?)```/gi;
  for (const match of content.matchAll(fencePattern)) {
    const block = match[0];
    const json = match[1];
    if (
      block &&
      json &&
      json.includes(QUESTIONNAIRE_TYPE) &&
      !candidates.some((candidate) => candidate.block === block)
    ) {
      candidates.push({ block, json });
    }
  }

  const trimmed = content.trim();
  if (
    trimmed.startsWith("{") &&
    trimmed.endsWith("}") &&
    (trimmed.includes(QUESTIONNAIRE_TYPE) ||
      (trimmed.includes('"question"') && trimmed.includes('"options"')))
  ) {
    candidates.push({ block: content, json: trimmed });
  }

  return candidates;
}

export function extractClarificationQuestionnaire(
  content: string,
): ExtractedClarificationQuestionnaire | null {
  for (const candidate of collectCandidates(content)) {
    const payload = parsePayload(candidate.json.trim());
    if (!payload) continue;
    return {
      payload,
      visibleContent: content.replace(candidate.block, "").trim(),
    };
  }
  return null;
}

function findOption(
  question: ClarificationQuestionnaireQuestion,
  value: string | undefined,
): ClarificationQuestionnaireOption | undefined {
  if (!value) return undefined;
  return question.options.find((option) => option.value === value);
}

function submitQuickReply(text: string, sourceMessageId?: string) {
  window.dispatchEvent(
    new CustomEvent("octopus:quick-reply", {
      detail: { text, sourceMessageId },
    }),
  );
}

function optionLetter(index: number) {
  return OPTION_LETTERS[index] ?? String(index + 1);
}

export function ClarificationQuestionnaire({
  active,
  className,
  onSubmitText,
  payload,
  sourceMessageId,
}: {
  active: boolean;
  className?: string;
  onSubmitText?: (text: string) => void;
  payload: ClarificationQuestionnairePayload;
  sourceMessageId?: string;
}) {
  const { t } = useI18n();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [dismissed, setDismissed] = useState(false);
  const current = payload.questions[step] ?? payload.questions[0];
  const selected = current ? answers[current.id] : undefined;
  const isLast = step >= payload.questions.length - 1;
  const submitLabel =
    payload.submitLabel ?? t.clarificationQuestionnaire.continueLabel;

  useEffect(() => {
    if (!active) return;
    setStep(0);
    setAnswers({});
    setDismissed(false);
  }, [active, payload]);

  if (!active || dismissed || !current) return null;

  const buildClarificationReply = () => {
    const lines = payload.questions
      .map((question) => {
        const option = findOption(question, answers[question.id]);
        if (!option) return null;
        return `- ${question.title.replace(/[?？]$/, "")}: ${option.label}`;
      })
      .filter((line): line is string => Boolean(line));

    return [
      t.clarificationQuestionnaire.completedHeader,
      ...lines,
      "",
      t.clarificationQuestionnaire.continuePrompt,
    ]
      .filter(Boolean)
      .join("\n");
  };

  const sendText = (text: string) => {
    if (onSubmitText) {
      onSubmitText(text);
    } else {
      submitQuickReply(text, sourceMessageId);
    }
    setDismissed(true);
  };

  const submit = () => {
    if (!selected) return;
    sendText(buildClarificationReply());
  };

  const continueOrSubmit = () => {
    if (!selected) return;
    if (isLast) {
      submit();
      return;
    }
    setStep((value) => Math.min(payload.questions.length - 1, value + 1));
  };

  return (
    <div
      aria-label={t.clarificationQuestionnaire.title}
      role="region"
      className={cn(
        "mt-4 flex min-h-[330px] w-full flex-col rounded-lg border border-border-default bg-background px-4 py-4 shadow-[0_10px_34px_rgba(15,23,42,0.08)] sm:min-h-[360px] sm:px-6 sm:py-5",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <MessageSquareTextIcon className="size-5 shrink-0 text-muted-foreground" />
          <h3 className="truncate text-base font-medium tracking-normal text-foreground">
            {t.clarificationQuestionnaire.title}
          </h3>
        </div>
        {payload.questions.length > 1 && (
          <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
            {step + 1} / {payload.questions.length}
          </span>
        )}
      </div>

      <div className="mt-6 flex items-baseline gap-4">
        <span className="w-7 shrink-0 text-base font-semibold text-foreground">
          {step + 1}.
        </span>
        <h4 className="text-[17px] font-semibold leading-7 tracking-normal text-foreground sm:text-lg">
          {current.title}
        </h4>
      </div>

      <div className="mt-5 grid gap-3 sm:pl-11">
        {current.options.map((option, index) => {
          const checked = selected === option.value;
          return (
            <button
              key={`${option.value}-${index}`}
              type="button"
              aria-pressed={checked}
              onClick={() =>
                setAnswers((value) => ({
                  ...value,
                  [current.id]: option.value,
                }))
              }
              className={cn(
                "group flex min-h-11 w-full items-start gap-3 rounded-md border px-1.5 py-1.5 text-left transition-colors sm:px-2",
                checked
                  ? "border-primary/40 bg-primary/5"
                  : "border-transparent hover:bg-muted/45",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-background text-sm font-semibold text-muted-foreground transition-colors",
                  checked
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border group-hover:border-foreground/20",
                )}
              >
                {optionLetter(index)}
              </span>
              <span className="min-w-0 flex-1 py-0.5">
                <span className="block text-base font-medium leading-7 text-foreground sm:text-base">
                  {option.label}
                </span>
                {option.description && (
                  <span className="mt-0.5 block text-sm leading-6 text-muted-foreground">
                    {option.description}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-auto flex flex-col gap-3 pt-8 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <SparklesIcon className="size-4 text-foreground" />
          <span>{t.clarificationQuestionnaire.recommended}</span>
        </div>
        <div className="flex items-center justify-end gap-2">
          {step > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="px-2 text-sm text-muted-foreground"
              onClick={() => setStep((value) => Math.max(0, value - 1))}
            >
              {t.clarificationQuestionnaire.previous}
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="px-2 text-sm text-muted-foreground hover:text-foreground"
            onClick={() => setDismissed(true)}
          >
            {t.clarificationQuestionnaire.cancel}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!selected}
            className="h-8 rounded-md px-3 text-sm"
            onClick={continueOrSubmit}
          >
            {isLast ? submitLabel : t.clarificationQuestionnaire.continueLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
