import { Clock3Icon, SendIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  ClarificationQuestionnaire,
  extractClarificationQuestionnaire,
} from "../clarification-questionnaire";

interface ParsedOption {
  key: string;
  label: string;
}

interface ClarificationChoice {
  key: string;
  label: string;
  detail: string;
  text: string;
}

interface ParsedClarification {
  choices: ClarificationChoice[];
  defaultChoice: ClarificationChoice;
}

const AUTO_SUBMIT_SECONDS = 20;
const CIRCLED_DIGITS = "①②③④⑤⑥⑦⑧⑨";

function cleanOptionText(text: string) {
  return text.replace(/\s+/g, " ").trim();
}

export function parseClarificationChoices(
  content: string,
): ParsedClarification | null {
  const lines = content.split(/\r?\n/);
  const letterOptions: ParsedOption[] = [];
  const digitOptions: ParsedOption[] = [];

  for (const line of lines) {
    const letter = line.match(/^\s*([A-H])[\.\)、:：]\s*(.+)$/i);
    if (letter?.[1] && letter[2]) {
      letterOptions.push({
        key: letter[1].toUpperCase(),
        label: cleanOptionText(letter[2]),
      });
      continue;
    }

    const digit = line.match(new RegExp(`^\\s*([${CIRCLED_DIGITS}])\\s*(.+)$`));
    if (digit?.[1] && digit[2]) {
      digitOptions.push({
        key: digit[1],
        label: cleanOptionText(digit[2]),
      });
    }
  }

  if (letterOptions.length === 0 && digitOptions.length === 0) return null;
  if (
    !/确认|选一个|选择|调研对象|调研目的|clarify|choose|confirm/i.test(content)
  ) {
    return null;
  }

  const choices: ClarificationChoice[] = [];
  if (letterOptions.length > 0 && digitOptions.length > 0) {
    for (const letter of letterOptions.slice(0, 4)) {
      for (const digit of digitOptions.slice(0, 4)) {
        choices.push({
          key: `${letter.key}${digit.key}`,
          label: `${letter.key}${digit.key}`,
          detail: `${letter.label} / ${digit.label}`,
          text: `${letter.key}${digit.key}`,
        });
      }
    }
  } else {
    for (const option of [...letterOptions, ...digitOptions].slice(0, 8)) {
      choices.push({
        key: option.key,
        label: option.key,
        detail: option.label,
        text: option.key,
      });
    }
  }

  const defaultChoice = choices[0];
  return defaultChoice ? { choices, defaultChoice } : null;
}

function submitQuickReply(text: string, messageId?: string) {
  window.dispatchEvent(
    new CustomEvent("octopus:quick-reply", {
      detail: { text, sourceMessageId: messageId },
    }),
  );
}

export function ClarificationChoiceCard({
  content,
  active,
  messageId,
  className,
}: {
  content: string;
  active: boolean;
  messageId?: string;
  className?: string;
}) {
  const { t } = useI18n();
  const questionnaire = useMemo(
    () => extractClarificationQuestionnaire(content),
    [content],
  );
  const parsed = useMemo(
    () => (questionnaire ? null : parseClarificationChoices(content)),
    [content, questionnaire],
  );
  const [secondsLeft, setSecondsLeft] = useState(AUTO_SUBMIT_SECONDS);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    setSecondsLeft(AUTO_SUBMIT_SECONDS);
    setSubmitted(false);
  }, [messageId, content]);

  useEffect(() => {
    if (!active || !parsed || submitted) return;
    const timer = window.setInterval(() => {
      setSecondsLeft((current) => {
        if (current <= 1) {
          window.clearInterval(timer);
          setSubmitted(true);
          submitQuickReply(parsed.defaultChoice.text, messageId);
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active, messageId, parsed, submitted]);

  if (!active) return null;

  if (questionnaire) {
    return (
      <ClarificationQuestionnaire
        active={active}
        payload={questionnaire.payload}
        sourceMessageId={messageId}
        className={className}
      />
    );
  }

  if (!parsed) return null;

  return (
    <div
      className={cn(
        "mt-3 rounded-lg border border-border/70 bg-muted/25 p-3",
        className,
      )}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{t.conversation.clarificationChoose}</span>
        <span className="inline-flex items-center gap-1">
          <Clock3Icon className="size-3.5" />
          {t.conversation.clarificationAutoSubmit(secondsLeft)}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {parsed.choices.map((choice, index) => (
          <Button
            key={`${choice.key}-${index}`}
            type="button"
            variant={index === 0 ? "default" : "outline"}
            className="h-auto justify-start gap-2 rounded-md px-3 py-2 text-left"
            disabled={submitted}
            onClick={() => {
              setSubmitted(true);
              submitQuickReply(choice.text, messageId);
            }}
          >
            <SendIcon className="size-3.5 shrink-0" />
            <span className="min-w-0">
              <span className="block text-xs font-semibold">
                {choice.label}
              </span>
              <span className="block truncate text-[11px] opacity-80">
                {choice.detail}
              </span>
            </span>
          </Button>
        ))}
      </div>
    </div>
  );
}
