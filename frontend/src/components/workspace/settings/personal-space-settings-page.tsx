import { FlaskConicalIcon, HammerIcon, SparklesIcon } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type PersonalMode = "general" | "build" | "research";

const COPY = {
  zh: {
    title: "个人空间",
    description: "设置未绑定项目目录时的默认工作方式和长期偏好。",
    defaultMode: "默认工作模式",
    defaultModeDescription:
      "新建个人任务时自动采用；仍可在输入框下方临时切换。",
    remember: "记住输入框中的模式选择",
    rememberDescription: "开启后，最近选择的模式会成为下一个个人任务的默认值。",
    instructions: "自定义工作规则",
    instructionsDescription:
      "这些规则只加入个人空间任务，不影响绑定的项目目录。",
    placeholder:
      "例如：研究时优先中文来源；构建成果统一放进 outputs/；回答保持简洁……",
    count: (count: number) => `${count}/2000`,
    modes: {
      general: ["通用", "日常对话与灵活任务"],
      build: ["构建", "产出可运行成果并验证"],
      research: ["研究", "多源调研、核验与报告"],
    },
  },
  en: {
    title: "Personal space",
    description: "Choose defaults for tasks without a bound project folder.",
    defaultMode: "Default work mode",
    defaultModeDescription:
      "Applied to new personal tasks; you can still switch in the composer.",
    remember: "Remember composer mode changes",
    rememberDescription:
      "The latest selection becomes the default for the next personal task.",
    instructions: "Custom work rules",
    instructionsDescription:
      "These rules apply only to personal space, never to bound projects.",
    placeholder:
      "For example: prefer primary sources; put build outputs in outputs/; keep replies concise…",
    count: (count: number) => `${count}/2000`,
    modes: {
      general: ["General", "Everyday conversation and flexible tasks"],
      build: ["Build", "Create and verify runnable artifacts"],
      research: ["Research", "Multi-source research and reports"],
    },
  },
  ja: {
    title: "個人スペース",
    description: "プロジェクト未接続時の既定の作業方法と継続設定を指定します。",
    defaultMode: "既定の作業モード",
    defaultModeDescription:
      "新しい個人タスクに適用され、入力欄から一時的に変更できます。",
    remember: "入力欄で選んだモードを記憶",
    rememberDescription: "最後に選んだモードを次の個人タスクの既定値にします。",
    instructions: "カスタム作業ルール",
    instructionsDescription:
      "個人スペースだけに適用され、接続済みプロジェクトには影響しません。",
    placeholder:
      "例：一次情報を優先する、成果物は outputs/ に置く、回答は簡潔にする…",
    count: (count: number) => `${count}/2000`,
    modes: {
      general: ["汎用", "日常の会話と柔軟なタスク"],
      build: ["構築", "実行可能な成果物を作成・検証"],
      research: ["研究", "複数ソースの調査とレポート"],
    },
  },
  ko: {
    title: "개인 공간",
    description:
      "프로젝트 폴더가 연결되지 않은 작업의 기본 방식과 지속 설정을 지정합니다.",
    defaultMode: "기본 작업 모드",
    defaultModeDescription:
      "새 개인 작업에 적용되며 입력창에서 임시로 변경할 수 있습니다.",
    remember: "입력창의 모드 선택 기억",
    rememberDescription:
      "마지막 선택을 다음 개인 작업의 기본값으로 사용합니다.",
    instructions: "사용자 지정 작업 규칙",
    instructionsDescription:
      "개인 공간에만 적용되며 연결된 프로젝트에는 영향을 주지 않습니다.",
    placeholder:
      "예: 1차 출처 우선, 결과물은 outputs/에 저장, 답변은 간결하게…",
    count: (count: number) => `${count}/2000`,
    modes: {
      general: ["일반", "일상 대화와 유연한 작업"],
      build: ["빌드", "실행 가능한 결과물 생성 및 검증"],
      research: ["리서치", "다중 출처 조사와 보고서"],
    },
  },
} as const;

const MODE_OPTIONS = [
  { id: "general" as const, icon: SparklesIcon },
  { id: "build" as const, icon: HammerIcon },
  { id: "research" as const, icon: FlaskConicalIcon },
];

export default function PersonalSpaceSettingsPage() {
  const { locale } = useI18n();
  const language = locale.slice(0, 2).toLowerCase();
  const copy =
    language === "zh"
      ? COPY.zh
      : language === "ja"
        ? COPY.ja
        : language === "ko"
          ? COPY.ko
          : COPY.en;
  const [settings, setSettings] = useLocalSettings();
  const personal = settings.personal_space;

  const setMode = (default_mode: PersonalMode) => {
    setSettings("personal_space", { default_mode });
  };

  return (
    <SettingsSection title={copy.title} description={copy.description}>
      <div className="space-y-6">
        <section className="space-y-3" aria-labelledby="personal-default-mode">
          <div>
            <h3 id="personal-default-mode" className="text-sm font-medium">
              {copy.defaultMode}
            </h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {copy.defaultModeDescription}
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {MODE_OPTIONS.map(({ id, icon: Icon }) => {
              const [label, description] = copy.modes[id];
              const active = personal.default_mode === id;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={active}
                  aria-label={label}
                  onClick={() => setMode(id)}
                  className={cn(
                    "rounded-xl border p-3 text-left transition-colors",
                    active
                      ? "border-primary/45 bg-primary/8 ring-1 ring-primary/15"
                      : "border-border-default bg-card hover:bg-muted/40",
                  )}
                >
                  <Icon
                    className={cn(
                      "mb-2 size-4",
                      active ? "text-primary" : "text-muted-foreground",
                    )}
                  />
                  <div className="text-sm font-medium">{label}</div>
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    {description}
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <div className="flex items-center justify-between gap-4 rounded-xl border bg-card p-4">
          <div className="min-w-0">
            <p className="text-sm font-medium">{copy.remember}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {copy.rememberDescription}
            </p>
          </div>
          <Switch
            checked={personal.remember_last_mode}
            onCheckedChange={(remember_last_mode) =>
              setSettings("personal_space", { remember_last_mode })
            }
            aria-label={copy.remember}
          />
        </div>

        <section className="space-y-3" aria-labelledby="personal-instructions">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h3 id="personal-instructions" className="text-sm font-medium">
                {copy.instructions}
              </h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {copy.instructionsDescription}
              </p>
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">
              {copy.count(personal.custom_instructions.length)}
            </span>
          </div>
          <Textarea
            value={personal.custom_instructions}
            maxLength={2000}
            rows={6}
            placeholder={copy.placeholder}
            aria-label={copy.instructions}
            onChange={(event) =>
              setSettings("personal_space", {
                custom_instructions: event.target.value,
              })
            }
          />
        </section>
      </div>
    </SettingsSection>
  );
}
