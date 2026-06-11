
import {
  ArrowLeftIcon,
  BotIcon,
  BriefcaseBusinessIcon,
  CalendarDaysIcon,
  CheckCircleIcon,
  CheckIcon,
  DatabaseIcon,
  FileSearchIcon,
  InfoIcon,
  MoreHorizontalIcon,
  SaveIcon,
  SearchIcon,
  ShieldCheckIcon,
  TagIcon,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { ThreadProviders } from "@/components/workspace/messages/context";
import { swallow } from "@/core/utils/log";
import type { Agent } from "@/core/agents";
import { checkAgentName, getAgent } from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

type Step = "name" | "chat";
type SetupAgentStatus = "idle" | "requested" | "completed";
type AgentTemplate = {
  id: string;
  icon: React.ReactNode;
  name: string;
  nameSuggestion: string;
  description: string;
  prompt: string;
  integrations: string[];
  capabilities: string[];
};

const NAME_RE = /^[A-Za-z0-9-]+$/;
const SAVE_HINT_STORAGE_KEY = "octopus.agent-create.save-hint-seen";
const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];
const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "team-qa",
    icon: <BotIcon className="size-4" />,
    name: "团队聊天问答",
    nameSuggestion: "team-qa",
    description: "基于团队资料、群消息和共享文档回答问题。",
    prompt: "创建一个团队知识问答智能体。它需要读取团队提供的文档、历史讨论和项目资料，在团队消息中用简洁可靠的方式回答问题；遇到不确定内容要说明来源和置信度。",
    integrations: ["知识库", "团队消息", "Google Drive"],
    capabilities: [
      "整理团队文档并回答成员问题",
      "回答时标注依据和缺口",
      "把反复出现的问题沉淀成可复用知识",
    ],
  },
  {
    id: "digital-twin",
    icon: <BriefcaseBusinessIcon className="size-4" />,
    name: "真人数字分身",
    nameSuggestion: "digital-twin",
    description: "沉淀真实成员的经验、口吻、职责边界和可授权任务。",
    prompt:
      "创建一个真人数字分身智能体。它不是虚拟人设，而是某位真实成员的工作分身：需要记录该成员的角色职责、常用话术、决策偏好、禁区边界、可授权任务、必须回传本人确认的场景，并用自然对话协助团队完成日常工作。",
    integrations: ["个人资料", "知识库", "对话记录", "授权边界"],
    capabilities: [
      "沉淀真人的职责范围、表达口吻和决策偏好",
      "区分可自动处理、需本人确认、必须转人工的任务",
      "基于资料与历史对话回答团队问题",
      "在对外承诺、价格、合同和敏感事项上主动要求确认",
      "持续把真人反馈更新为更准确的工作边界",
    ],
  },
  {
    id: "morning-planner",
    icon: <CalendarDaysIcon className="size-4" />,
    name: "晨间计划",
    nameSuggestion: "morning-planner",
    description: "根据日历、任务和未结束会话规划当天安排。",
    prompt: "创建一个晨间计划智能体。每天根据我的日历、待办事项、未结束会话和优先级，生成当天可执行计划；需要识别冲突、建议时间块，并在任务变化时更新计划。",
    integrations: ["Calendar", "Todos", "会话历史"],
    capabilities: [
      "把分散任务转成当天计划",
      "识别截止日期和时间冲突",
      "跟踪未完成事项并滚动调整",
    ],
  },
  {
    id: "defect-triage",
    icon: <TagIcon className="size-4" />,
    name: "缺陷分诊",
    nameSuggestion: "defect-triage",
    description: "审查新报缺陷、判断优先级并写入跟踪器。",
    prompt: "创建一个缺陷分诊智能体。它需要阅读新提交的缺陷描述、日志和截图，判断影响范围与优先级，补全复现步骤，并把结论同步到团队缺陷跟踪器。",
    integrations: ["Linear", "Jira", "日志"],
    capabilities: [
      "补全复现步骤和影响范围",
      "给出优先级和负责方向",
      "把结论沉淀到缺陷跟踪器",
    ],
  },
  {
    id: "data-analyst",
    icon: <DatabaseIcon className="size-4" />,
    name: "数据分析",
    nameSuggestion: "data-analyst",
    description: "围绕分析目标组织数据、SQL、图表和质量检查。",
    prompt: "创建一个数据分析智能体。它需要把模糊的数据需求转成分析计划，检查数据集结构和异常，编写或修复 SQL，选择合适的图表或表格，并在分享前做质量检查。",
    integrations: ["Airtable", "Hex", "SQL"],
    capabilities: [
      "将模糊数据需求转化为分析计划",
      "检查数据集结构和异常",
      "编写或修复 SQL 和抽取逻辑",
      "选择最清晰的图表或表格",
      "分享前对分析进行压力测试",
    ],
  },
  {
    id: "exec-assistant",
    icon: <BriefcaseBusinessIcon className="size-4" />,
    name: "执行助理",
    nameSuggestion: "exec-assistant",
    description: "汇总日程、收件箱和项目进展，推动后续动作。",
    prompt: "创建一个执行助理智能体。它需要帮助我汇总日程、收件箱、会议纪要和项目进展，提炼需要我决策的事项，草拟回复，并持续跟进后续动作。",
    integrations: ["Mail", "Calendar", "Docs"],
    capabilities: [
      "汇总关键信息和待决策事项",
      "草拟回复和会议跟进",
      "把承诺事项转成可追踪任务",
    ],
  },
  {
    id: "knowledge-search",
    icon: <FileSearchIcon className="size-4" />,
    name: "知识搜索",
    nameSuggestion: "knowledge-search",
    description: "跨文档、网页和会话做可靠检索与答案归纳。",
    prompt: "创建一个知识搜索智能体。它需要跨本地知识库、网页资料和历史会话检索信息，归纳成可执行答案；对于时效性内容要主动搜索并给出来源。",
    integrations: ["Web", "Knowledge", "Files"],
    capabilities: [
      "跨来源检索并合并答案",
      "区分事实、推断和不确定性",
      "对时效性问题主动联网确认",
    ],
  },
];

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function suggestAgentName(text: string) {
  const words = text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 4);
  if (words.length === 0) return "custom-agent";
  return words.join("-").slice(0, 36).replace(/-+$/g, "") || "custom-agent";
}

async function getAgentWithRetry(agentName: string) {
  for (const delay of [0, ...AGENT_READ_RETRY_DELAYS_MS]) {
    if (delay > 0) {
      await wait(delay);
    }

    try {
      return await getAgent(agentName);
    } catch (e) { swallow(e); }
  }

  return null;
}

function buildTemplatePrompt(
  template: AgentTemplate,
  roleName?: string | null,
  roleFocus?: string | null,
  roleCapability?: string | null,
) {
  if (!roleName) return template.prompt;
  const context = [
    "",
    `目标岗位：${roleName}`,
    roleCapability ? `复合能力：${roleCapability}` : null,
    roleFocus ? `主要辅助：${roleFocus}` : null,
    "",
  ];
  if (template.id === "digital-twin") {
    return [
      template.prompt,
      ...context,
      "请把这个岗位分身拆成：职责范围、常用资料、可自动处理、需本人确认、禁区边界、输出口吻和首次训练清单。",
    ]
      .filter(Boolean)
      .join("\n");
  }
  return [
    template.prompt,
    ...context,
    "请基于这个岗位上下文生成专属 Agent：明确职责边界、默认工具、输出格式、需要沉淀的知识、不能自动承诺的风险事项和首次可执行任务。",
  ]
    .filter(Boolean)
    .join("\n");
}

export default function NewAgentPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedTemplateId = searchParams.get("template");
  const requestedRoleId = searchParams.get("roleId");
  const requestedRoleName = searchParams.get("role");
  const requestedRoleFocus = searchParams.get("focus");
  const requestedRoleCapability = searchParams.get("capability");
  const initialTemplateId = useMemo(() => {
    if (
      requestedTemplateId &&
      AGENT_TEMPLATES.some((template) => template.id === requestedTemplateId)
    ) {
      return requestedTemplateId;
    }
    return AGENT_TEMPLATES[0]?.id ?? "";
  }, [requestedTemplateId]);

  const [step, setStep] = useState<Step>("name");
  const [nameInput, setNameInput] = useState("");
  const [agentBrief, setAgentBrief] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] =
    useState<string>(initialTemplateId);
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [agent, setAgent] = useState<Agent | null>(null);
  const [showSaveHint, setShowSaveHint] = useState(false);
  const [setupAgentStatus, setSetupAgentStatus] =
    useState<SetupAgentStatus>("idle");

  const threadId = useMemo(() => uuid(), []);
  const selectedTemplate = useMemo(
    () =>
      AGENT_TEMPLATES.find((template) => template.id === selectedTemplateId) ??
      AGENT_TEMPLATES[0],
    [selectedTemplateId],
  );

  useEffect(() => {
    if (!requestedTemplateId) return;
    const requestedTemplate = AGENT_TEMPLATES.find(
      (template) => template.id === requestedTemplateId,
    );
    if (!requestedTemplate) return;
    setSelectedTemplateId(requestedTemplate.id);
    setAgentBrief((current) =>
      current.trim()
        ? current
        : buildTemplatePrompt(
            requestedTemplate,
            requestedRoleName,
            requestedRoleFocus,
            requestedRoleCapability,
          ),
    );
    setNameInput((current) =>
      current.trim()
        ? current
        : requestedRoleId ?? requestedTemplate.nameSuggestion,
    );
  }, [
    requestedRoleCapability,
    requestedRoleFocus,
    requestedRoleId,
    requestedRoleName,
    requestedTemplateId,
  ]);

  const [thread, sendMessage] = useThreadStream({
    threadId: step === "chat" ? threadId : undefined,
    context: {
      mode: "chat",
      is_bootstrap: true,
    },
    onFinish() {
      if (!agent && setupAgentStatus === "requested") {
        setSetupAgentStatus("idle");
      }
    },
    onToolEnd({ name }) {
      if (name !== "setup_agent" || !agentName) return;
      setSetupAgentStatus("completed");
      void getAgentWithRetry(agentName).then((fetched) => {
        if (fetched) {
          setAgent(fetched);
          return;
        }

        toast.error(t.agents.agentCreatedPendingRefresh);
      });
    },
  });

  useEffect(() => {
    if (typeof window === "undefined" || step !== "chat") {
      return;
    }
    if (window.localStorage.getItem(SAVE_HINT_STORAGE_KEY) === "1") {
      return;
    }
    setShowSaveHint(true);
    window.localStorage.setItem(SAVE_HINT_STORAGE_KEY, "1");
  }, [step]);

  const handleConfirmName = useCallback(async () => {
    const brief = agentBrief.trim();
    const trimmed = (nameInput.trim() || suggestAgentName(brief)).toLowerCase();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch (err) {
      swallow(err);
      if (err instanceof TypeError && err.message === "Failed to fetch") {
        setNameError(t.agents.nameStepNetworkError);
      } else {
        setNameError(t.agents.nameStepCheckError);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }

    setAgentName(trimmed);
    setStep("chat");
    const templateBlock = selectedTemplate
      ? [
          `参考模板: ${selectedTemplate.name}`,
          `适用集成: ${selectedTemplate.integrations.join(", ")}`,
          "建议能力:",
          ...selectedTemplate.capabilities.map((capability) => `- ${capability}`),
        ].join("\n")
      : "";
    await sendMessage(threadId, {
      text: [
        t.agents.nameStepBootstrapMessage.replace("{name}", trimmed),
        "",
        "请根据下面的草案创建这个智能体的 SOUL、工具边界和初始行为规范。模板只是参考，不要强制套模板；如果用户目标与模板冲突，以用户目标为准。",
        "",
        "[用户描述]",
        brief || "用户尚未补充更多描述，请基于参考模板生成一个简洁可用的初稿。",
        "",
        templateBlock,
      ].filter(Boolean).join("\n"),
      files: [],
    });
  }, [
    agentBrief,
    nameInput,
    sendMessage,
    selectedTemplate,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepBootstrapMessage,
    t.agents.nameStepCheckError,
    t.agents.nameStepInvalidError,
    threadId,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const handleSelectTemplate = useCallback((template: AgentTemplate) => {
    setSelectedTemplateId(template.id);
    setAgentBrief(template.prompt);
    setNameInput((current) => current.trim() ? current : template.nameSuggestion);
    setNameError("");
  }, []);

  const handleChatSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || thread.isLoading) return;
      await sendMessage(
        threadId,
        { text: trimmed, files: [] },
        { agent_name: agentName },
      );
    },
    [agentName, sendMessage, thread.isLoading, threadId],
  );

  const handleSaveAgent = useCallback(async () => {
    if (
      !agentName ||
      agent ||
      thread.isLoading ||
      setupAgentStatus !== "idle"
    ) {
      return;
    }

    setSetupAgentStatus("requested");
    setShowSaveHint(false);
    try {
      await sendMessage(
        threadId,
        { text: t.agents.saveCommandMessage, files: [] },
        { agent_name: agentName },
        { additionalKwargs: { hide_from_ui: true } },
      );
      toast.success(t.agents.saveRequested);
    } catch (error) {
      setSetupAgentStatus("idle");
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agent,
    agentName,
    sendMessage,
    setupAgentStatus,
    t.agents.saveCommandMessage,
    t.agents.saveRequested,
    thread.isLoading,
    threadId,
  ]);

  const header = (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => navigate("/workspace/agents")}
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-semibold">{t.agents.createPageTitle}</h1>
      </div>

      {step === "chat" ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t.agents.more}>
              <MoreHorizontalIcon className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              onSelect={() => void handleSaveAgent()}
              disabled={
                !!agent || thread.isLoading || setupAgentStatus !== "idle"
              }
            >
              <SaveIcon className="h-4 w-4" />
              {setupAgentStatus === "requested"
                ? t.agents.saving
                : t.agents.save}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </header>
  );

  if (step === "name") {
    return (
      <div className="flex size-full flex-col">
        {header}
        <main className="min-h-0 flex-1 overflow-y-auto bg-muted/10 px-4 py-8">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
            <section className="mx-auto w-full max-w-4xl text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-border/70 bg-background shadow-sm">
                <BotIcon className="size-7 text-primary" />
              </div>
              <h2 className="text-3xl font-semibold tracking-tight">
                创建新智能体
              </h2>
              <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                先描述它应该做什么。Octopus 会把一句话目标转成可编辑草案；模板只负责预填能力边界，不会强制锁死工作流。
              </p>

              <div className="mt-7 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-sm">
                <div className="flex items-start gap-3 px-4 py-3">
                  <button
                    type="button"
                    className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    title="添加资料"
                    aria-label="添加资料"
                  >
                    +
                  </button>
                  <textarea
                    autoFocus
                    value={agentBrief}
                    onChange={(event) => {
                      const value = event.target.value;
                      setAgentBrief(value);
                      if (!nameInput.trim()) {
                        setNameInput(suggestAgentName(value));
                      }
                    }}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        (event.metaKey || event.ctrlKey) &&
                        !isIMEComposing(event)
                      ) {
                        event.preventDefault();
                        void handleConfirmName();
                      }
                    }}
                    placeholder="描述智能体应该做什么"
                    className="min-h-20 flex-1 resize-none bg-transparent py-2 text-left text-base outline-none placeholder:text-muted-foreground/70"
                  />
                  <button
                    type="button"
                    className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    title="语音输入"
                    aria-label="语音输入"
                  >
                    <BotIcon className="size-4" />
                  </button>
                </div>
                <div className="flex flex-col gap-3 border-t border-border/50 px-4 py-3 text-left sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      Agent ID
                    </span>
                    <Input
                      placeholder={t.agents.nameStepPlaceholder}
                      value={nameInput}
                      onChange={(e) => {
                        setNameInput(e.target.value.toLowerCase());
                        setNameError("");
                      }}
                      onKeyDown={handleNameKeyDown}
                      className={cn(
                        "h-8 w-56 rounded-full border-border/70 bg-muted/20 text-xs transition-colors",
                        nameError && "border-destructive",
                      )}
                    />
                  </div>
                  <Button
                    className="rounded-full px-5"
                    onClick={() => void handleConfirmName()}
                    disabled={(!agentBrief.trim() && !selectedTemplate) || isCheckingName}
                  >
                    {isCheckingName ? "检查中..." : "生成草案"}
                  </Button>
                </div>
              </div>
              {nameError ? (
                <p className="mt-2 text-left text-sm text-destructive">
                  {nameError}
                </p>
              ) : null}
            </section>

            <section className="grid min-h-[420px] gap-4 lg:grid-cols-[360px_1fr]">
              <div className="rounded-2xl border border-border/70 bg-background p-3 shadow-sm">
                <div className="relative mb-3">
                  <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    readOnly
                    value=""
                    placeholder="搜索模板"
                    className="h-11 rounded-xl bg-muted/20 pl-9"
                  />
                </div>
                <div className="max-h-[520px] space-y-1 overflow-y-auto pr-1">
                  {AGENT_TEMPLATES.map((template) => {
                    const active = template.id === selectedTemplateId;
                    return (
                      <button
                        key={template.id}
                        type="button"
                        onClick={() => handleSelectTemplate(template)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors",
                          active
                            ? "bg-muted text-foreground"
                            : "text-muted-foreground hover:bg-muted/55 hover:text-foreground",
                        )}
                      >
                        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-background text-primary ring-1 ring-border/70">
                          {template.icon}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">
                            {template.name}
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                            {template.description}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-2xl border border-border/70 bg-background p-8 shadow-sm">
                {selectedTemplate ? (
                  <div className="flex h-full flex-col">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <span className="mb-5 flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/15">
                          {selectedTemplate.icon}
                        </span>
                        <h3 className="text-2xl font-semibold">
                          {selectedTemplate.name}
                        </h3>
                        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                          {selectedTemplate.description}
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        className="rounded-full"
                        onClick={() => handleSelectTemplate(selectedTemplate)}
                      >
                        使用模板
                      </Button>
                    </div>

                    <div className="mt-8">
                      <div className="mb-3 text-sm font-medium">适用于</div>
                      <div className="flex flex-wrap gap-2">
                        {selectedTemplate.integrations.map((integration) => (
                          <span
                            key={integration}
                            className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-muted/15 px-3 py-1 text-sm"
                          >
                            <ShieldCheckIcon className="size-3.5 text-primary" />
                            {integration}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="mt-8">
                      <div className="mb-3 text-sm font-medium">功能</div>
                      <div className="divide-y divide-border/60">
                        {selectedTemplate.capabilities.map((capability) => (
                          <div
                            key={capability}
                            className="flex items-center gap-3 py-3 text-sm"
                          >
                            <CheckIcon className="size-4 text-muted-foreground" />
                            <span>{capability}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="mt-auto pt-8">
                      <div className="rounded-xl border border-dashed border-border/70 bg-muted/15 p-4 text-xs leading-5 text-muted-foreground">
                        创建后会进入草案对话。你可以继续补充工具、权限、知识源、输出风格和验证方式；满意后再保存为真正可用的 Agent。
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </section>
          </div>
        </main>
      </div>
    );
  }

  return (
    <ThreadProviders thread={thread}>
      <ArtifactsProvider>
        <div className="flex size-full flex-col">
          {header}

          <main className="flex min-h-0 flex-1 flex-col">
            {showSaveHint ? (
              <div className="px-4 pt-4">
                <div className="mx-auto w-full max-w-(--container-width-md)">
                  <Alert>
                    <InfoIcon className="h-4 w-4" />
                    <AlertDescription>{t.agents.saveHint}</AlertDescription>
                  </Alert>
                </div>
              </div>
            ) : null}

            <div className="flex min-h-0 flex-1 justify-center">
              <MessageList
                className={cn("size-full", showSaveHint ? "pt-4" : "pt-10")}
                threadId={threadId}
                thread={thread}
                mode="chat"
              />
            </div>

            <div className="bg-background flex shrink-0 justify-center border-t px-4 py-4">
              <div className="w-full max-w-(--container-width-md)">
                {agent ? (
                  <div className="flex flex-col items-center gap-4 rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-transparent py-8 text-center">
                    <div className="flex size-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5">
                      <CheckCircleIcon className="text-primary h-6 w-6" />
                    </div>
                    <p className="font-semibold">{t.agents.agentCreated}</p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() =>
                          navigate(
                            `/workspace/agents/${agentName}/chats/new`,
                          )
                        }
                      >
                        {t.agents.startChatting}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => navigate("/workspace/agents")}
                      >
                        {t.agents.backToGallery}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <PromptInput
                    onSubmit={({ text }) => void handleChatSubmit(text)}
                  >
                    <PromptInputTextarea
                      autoFocus
                      placeholder={t.agents.createPageSubtitle}
                      disabled={thread.isLoading}
                    />
                    <PromptInputFooter className="justify-end">
                      <PromptInputSubmit disabled={thread.isLoading} />
                    </PromptInputFooter>
                  </PromptInput>
                )}
              </div>
            </div>
          </main>
        </div>
      </ArtifactsProvider>
    </ThreadProviders>
  );
}
