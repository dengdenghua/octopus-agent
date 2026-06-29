import {
  ArrowLeftIcon,
  BotIcon,
  BriefcaseBusinessIcon,
  CalendarDaysIcon,
  CheckCircleIcon,
  DatabaseIcon,
  FileSearchIcon,
  InfoIcon,
  MoreHorizontalIcon,
  SaveIcon,
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
import { taskWorkspaceRoute } from "@/core/router/task-workspace-route";
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

type AgentRolePreset = {
  id: string;
  label: string;
  nameSuggestion: string;
  brief: string;
};

type AgentScenePreset = {
  id: string;
  label: string;
  brief: string;
  permissions: string[];
};

type AgentCapabilityPack = {
  id: string;
  label: string;
  arms: string[];
  skills: string[];
  brief: string;
};

const NAME_RE = /^[A-Za-z0-9-]+$/;
const SAVE_HINT_STORAGE_KEY = "octopus.agent-create.save-hint-seen";
const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];
const AGENT_GENERATOR_SKILL_ID = "agent-generator";
const ROLE_PRESETS: AgentRolePreset[] = [
  {
    id: "operator",
    label: "工作流执行者",
    nameSuggestion: "workflow-operator",
    brief: "负责把用户目标拆成步骤，调用工具执行，并在关键节点回报进展。",
  },
  {
    id: "analyst",
    label: "分析顾问",
    nameSuggestion: "insight-analyst",
    brief: "负责调研、分析、归纳证据，并输出结构化判断和下一步行动。",
  },
  {
    id: "creator",
    label: "内容创作",
    nameSuggestion: "content-creator",
    brief: "负责把模糊想法转成可发布内容、脚本、文案和视觉方向。",
  },
  {
    id: "assistant",
    label: "个人助理",
    nameSuggestion: "personal-assistant",
    brief: "负责整理日程、消息、文件和待办，帮助用户保持事务有序推进。",
  },
];
const SCENE_PRESETS: AgentScenePreset[] = [
  {
    id: "workspace",
    label: "工作区协作",
    brief: "主要在团队、知识库、项目资料和共享上下文中工作。",
    permissions: ["读取工作区资料", "写入草案和任务", "高风险外部动作需确认"],
  },
  {
    id: "research",
    label: "深度调研",
    brief: "需要搜索网页、比对来源、整理证据链并给出判断。",
    permissions: ["允许联网搜索", "必须标注来源", "不确定结论需显式说明"],
  },
  {
    id: "automation",
    label: "自动化执行",
    brief: "适合重复流程、表格处理、文件整理和跨工具串联。",
    permissions: ["允许本地/工具操作", "写入前先预览", "删除和发送动作需确认"],
  },
  {
    id: "chat",
    label: "对话陪伴",
    brief: "重视长期记忆、口吻一致性、角色设定和互动边界。",
    permissions: ["遵循角色口吻", "保留安全边界", "不伪造真实身份"],
  },
];
const CAPABILITY_PACKS: AgentCapabilityPack[] = [
  {
    id: "knowledge",
    label: "知识库",
    arms: ["knowledge", "files"],
    skills: ["read_knowledge", "summarize_docs", "cite_sources"],
    brief: "读取并归纳知识库、文件和历史上下文。",
  },
  {
    id: "web",
    label: "网页调研",
    arms: ["browser", "search"],
    skills: ["web_search", "open_url", "extract_evidence"],
    brief: "联网搜索、打开网页、抽取来源和事实证据。",
  },
  {
    id: "workspace-tools",
    label: "工作区工具",
    arms: ["tasks", "calendar", "team"],
    skills: ["create_task", "read_calendar", "draft_update"],
    brief: "处理任务、日程、团队消息和项目更新。",
  },
  {
    id: "local",
    label: "本机操作",
    arms: ["computer", "filesystem"],
    skills: ["inspect_files", "edit_file", "run_command"],
    brief: "在用户确认下读取文件、修改草案或执行本地命令。",
  },
];
const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: "team-qa",
    icon: <BotIcon className="size-4" />,
    name: "团队聊天问答",
    nameSuggestion: "team-qa",
    description: "基于团队资料、群消息和共享文档回答问题。",
    prompt:
      "创建一个团队知识问答智能体。它需要读取团队提供的文档、历史讨论和项目资料，在团队消息中用简洁可靠的方式回答问题；遇到不确定内容要说明来源和置信度。",
    integrations: ["知识库", "团队消息", "Google Drive"],
    capabilities: [
      "整理团队文档并回答成员问题",
      "回答时标注依据和缺口",
      "把反复出现的问题沉淀成可复用知识",
    ],
  },
  {
    id: "morning-planner",
    icon: <CalendarDaysIcon className="size-4" />,
    name: "晨间计划",
    nameSuggestion: "morning-planner",
    description: "根据日历、任务和未结束会话规划当天安排。",
    prompt:
      "创建一个晨间计划智能体。每天根据我的日历、待办事项、未结束会话和优先级，生成当天可执行计划；需要识别冲突、建议时间块，并在任务变化时更新计划。",
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
    prompt:
      "创建一个缺陷分诊智能体。它需要阅读新提交的缺陷描述、日志和截图，判断影响范围与优先级，补全复现步骤，并把结论同步到团队缺陷跟踪器。",
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
    prompt:
      "创建一个数据分析智能体。它需要把模糊的数据需求转成分析计划，检查数据集结构和异常，编写或修复 SQL，选择合适的图表或表格，并在分享前做质量检查。",
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
    prompt:
      "创建一个执行助理智能体。它需要帮助我汇总日程、收件箱、会议纪要和项目进展，提炼需要我决策的事项，草拟回复，并持续跟进后续动作。",
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
    prompt:
      "创建一个知识搜索智能体。它需要跨本地知识库、网页资料和历史会话检索信息，归纳成可执行答案；对于时效性内容要主动搜索并给出来源。",
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
    } catch (e) {
      swallow(e);
    }
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
  return [
    template.prompt,
    ...context,
    "请基于这个岗位上下文生成专属 Agent：明确职责边界、默认工具、输出格式、需要沉淀的知识、不能自动承诺的风险事项和首次可执行任务。",
  ]
    .filter(Boolean)
    .join("\n");
}

function uniqueValues(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function buildGuidedConfigPrompt({
  role,
  scenes,
  packs,
  template,
}: {
  role: AgentRolePreset;
  scenes: AgentScenePreset[];
  packs: AgentCapabilityPack[];
  template?: AgentTemplate;
}) {
  const arms = uniqueValues(packs.flatMap((pack) => pack.arms));
  const skills = uniqueValues([
    AGENT_GENERATOR_SKILL_ID,
    ...packs.flatMap((pack) => pack.skills),
  ]);
  const permissions = uniqueValues(
    scenes.flatMap((scene) => scene.permissions),
  );
  return [
    `我想创建一个「${role.label}」Agent。`,
    "",
    "一句话目标：",
    role.brief,
    "",
    "主要场景：",
    ...scenes.map((scene) => `- ${scene.label}：${scene.brief}`),
    "",
    "请默认调用 agent-generator，把上面的简短描述扩写成可保存的 Agent 配置。",
    "",
    "配置偏好：",
    `- ARM：${arms.join(", ")}`,
    `- Skill 白名单：${skills.join(", ")}`,
    `- 权限边界：${permissions.join("；")}`,
    ...packs.map((pack) => `- 技能包：${pack.label} - ${pack.brief}`),
    "",
    template ? `启动模板：${template.name}。${template.description}` : null,
    "",
    "请生成 SOUL、工具边界、默认输出格式、首次可执行任务和需要用户确认的高风险动作。",
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
  const galleryReturnPath =
    searchParams.get("return") === "hud"
      ? "/workspace/agents?hud=1&surface=chat"
      : "/workspace/agents";
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
  const [selectedRolePresetId, setSelectedRolePresetId] = useState(
    ROLE_PRESETS[0]?.id ?? "",
  );
  const [selectedScenePresetIds, setSelectedScenePresetIds] = useState<
    string[]
  >(SCENE_PRESETS[0]?.id ? [SCENE_PRESETS[0].id] : []);
  const [selectedCapabilityPackIds, setSelectedCapabilityPackIds] = useState<
    string[]
  >(CAPABILITY_PACKS[0]?.id ? [CAPABILITY_PACKS[0].id] : []);
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
  const selectedRolePreset = useMemo(
    () =>
      ROLE_PRESETS.find((preset) => preset.id === selectedRolePresetId) ??
      ROLE_PRESETS[0],
    [selectedRolePresetId],
  );
  const selectedScenePresets = useMemo(
    () =>
      SCENE_PRESETS.filter((preset) =>
        selectedScenePresetIds.includes(preset.id),
      ),
    [selectedScenePresetIds],
  );
  const selectedCapabilityPacks = useMemo(
    () =>
      CAPABILITY_PACKS.filter((pack) =>
        selectedCapabilityPackIds.includes(pack.id),
      ),
    [selectedCapabilityPackIds],
  );
  const selectedArms = useMemo(
    () => uniqueValues(selectedCapabilityPacks.flatMap((pack) => pack.arms)),
    [selectedCapabilityPacks],
  );
  const selectedSkills = useMemo(
    () =>
      uniqueValues([
        AGENT_GENERATOR_SKILL_ID,
        ...selectedCapabilityPacks.flatMap((pack) => pack.skills),
      ]),
    [selectedCapabilityPacks],
  );
  const selectedPermissions = useMemo(
    () =>
      uniqueValues(selectedScenePresets.flatMap((scene) => scene.permissions)),
    [selectedScenePresets],
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
        : (requestedRoleId ?? requestedTemplate.nameSuggestion),
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
          ...selectedTemplate.capabilities.map(
            (capability) => `- ${capability}`,
          ),
        ].join("\n")
      : "";
    const configBlock = [
      `默认 Skill: ${AGENT_GENERATOR_SKILL_ID}`,
      `建议 ARM: ${selectedArms.join(", ") || "按任务需要收敛选择"}`,
      `建议 private_skills: ${selectedSkills.join(", ")}`,
      `权限边界: ${selectedPermissions.join("；") || "高风险动作需要用户确认"}`,
    ].join("\n");
    await sendMessage(threadId, {
      text: [
        t.agents.nameStepBootstrapMessage.replace("{name}", trimmed),
        "",
        "请使用 agent-generator Skill，根据用户的简短描述生成这个 Agent 的 SOUL、ARM/tool_groups、private_skills、权限边界、默认工作流和首次任务。模板只是参考，不要强制套模板；如果用户目标与模板冲突，以用户目标为准。",
        "",
        "[用户一句话描述]",
        brief ||
          "用户尚未补充更多描述，请基于参考模板生成一个简洁可用的 Agent 初稿。",
        "",
        "[配置偏好]",
        configBlock,
        "",
        templateBlock,
      ]
        .filter(Boolean)
        .join("\n"),
      files: [],
    });
  }, [
    agentBrief,
    nameInput,
    sendMessage,
    selectedTemplate,
    selectedArms,
    selectedPermissions,
    selectedSkills,
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
    setNameInput((current) =>
      current.trim() ? current : template.nameSuggestion,
    );
    setNameError("");
  }, []);

  const toggleSelectedScenePreset = useCallback((id: string) => {
    setSelectedScenePresetIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }, []);

  const toggleSelectedCapabilityPack = useCallback((id: string) => {
    setSelectedCapabilityPackIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }, []);

  const handleApplyGuidedConfig = useCallback(() => {
    if (
      !selectedRolePreset ||
      selectedScenePresets.length === 0 ||
      selectedCapabilityPacks.length === 0
    ) {
      return;
    }
    const nextBrief = buildGuidedConfigPrompt({
      role: selectedRolePreset,
      scenes: selectedScenePresets,
      packs: selectedCapabilityPacks,
      template: selectedTemplate,
    });
    setAgentBrief(nextBrief);
    setNameInput((current) =>
      current.trim() ? current : selectedRolePreset.nameSuggestion,
    );
    setNameError("");
  }, [
    selectedCapabilityPacks,
    selectedRolePreset,
    selectedScenePresets,
    selectedTemplate,
  ]);

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
          onClick={() => navigate(galleryReturnPath)}
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
      <div className="relative flex size-full items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_50%_18%,hsl(var(--primary)/0.08),transparent_34%),linear-gradient(to_bottom,hsl(var(--background)),hsl(var(--muted)/0.28))] p-6 text-white">
        <div className="pointer-events-none absolute inset-x-[20%] top-[8%] h-24 rounded-[50%] bg-primary/10 blur-3xl" />
        <div className="relative h-[min(700px,80vh)] w-[min(1080px,86vw)] overflow-hidden rounded-xl border border-white/10 bg-[#202020]/96 shadow-[0_28px_90px_rgba(15,23,42,0.28)] ring-1 ring-black/20 backdrop-blur-xl">
          <div className="pointer-events-none absolute inset-0 opacity-[0.09] [background-image:radial-gradient(circle_at_76%_28%,rgba(244,232,111,0.1),transparent_30%),linear-gradient(to_right,rgba(255,255,255,0.032)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.024)_1px,transparent_1px)] [background-size:100%_100%,40px_40px,40px_40px]" />
          <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-[#f4e86f]/24 to-transparent" />
          <div className="pointer-events-none absolute inset-x-14 bottom-0 h-px bg-gradient-to-r from-transparent via-white/8 to-transparent" />
          <div className="relative grid h-full grid-cols-[minmax(0,0.64fr)_minmax(260px,0.36fr)]">
            <section className="relative flex min-h-0 flex-col px-8 py-6 lg:px-10 lg:py-7">
              <div className="pointer-events-none absolute left-0 top-0 h-5 w-5 border-l border-t border-primary/60" />
              <div className="mb-6 flex shrink-0 items-center justify-between">
                <Button
                  aria-label={t.agentConfig.back}
                  className="h-8 w-8 shrink-0 rounded-sm text-white/72 hover:bg-white/8 hover:text-white"
                  size="icon"
                  variant="ghost"
                  onClick={() => navigate(galleryReturnPath)}
                >
                  <ArrowLeftIcon className="size-4" />
                </Button>
                <div className="flex items-center gap-2 rounded-sm border border-white/8 bg-white/[0.025] px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-white/48">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                  AGENT BLUEPRINT
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto pr-2 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.22)_transparent]">
                <div className="max-w-[560px] pb-6">
                  <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.24em] text-primary">
                    <span className="h-px w-6 bg-primary/70" />
                    CREATE AGENT
                  </div>
                  <h1 className="mt-4 text-5xl font-semibold leading-none text-white">
                    新建 Agent
                  </h1>
                  <p className="mt-3 text-lg font-medium leading-7 text-[#f4e86f]">
                    一句话描述目标，Agent Generator 自动补全配置
                  </p>

                  <div className="mt-6 rounded-sm border border-white/10 bg-black/16 p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/46">
                        SHORT BRIEF
                      </span>
                      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/30">
                        Ctrl/⌘ + Enter
                      </span>
                    </div>
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
                      placeholder="例如：帮我做竞品调研，每周输出机会点、风险提醒和下一步行动。"
                      className="min-h-[190px] w-full resize-none bg-transparent text-sm leading-7 text-white outline-none placeholder:text-white/30"
                    />
                  </div>

                  <div className="mt-4 grid grid-cols-[82px_1fr] items-center gap-3 rounded-sm border border-white/10 bg-white/[0.035] px-3 py-2">
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-white/42">
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
                        "h-8 rounded-sm border-white/10 bg-black/20 font-mono text-xs text-white placeholder:text-white/25",
                        nameError && "border-destructive",
                      )}
                    />
                  </div>

                  {nameError ? (
                    <p className="mt-2 text-xs leading-5 text-destructive">
                      {nameError}
                    </p>
                  ) : null}

                  <div className="mt-5 flex items-center gap-2">
                    <Button
                      className="h-9 rounded-sm bg-[#f4e86f] px-5 text-[#232323] hover:bg-[#fff27c]"
                      onClick={() => void handleConfirmName()}
                      disabled={
                        (!agentBrief.trim() && !selectedTemplate) ||
                        isCheckingName
                      }
                    >
                      {isCheckingName ? "检查中..." : "生成 Agent"}
                    </Button>
                    <Button
                      className="h-9 rounded-sm border border-white/14 bg-black/30 px-4 text-white/86 hover:border-white/24 hover:bg-white/8 hover:text-white"
                      variant="outline"
                      onClick={() => navigate(galleryReturnPath)}
                    >
                      返回
                    </Button>
                  </div>
                </div>
              </div>
            </section>

            <section className="relative min-h-0 overflow-hidden border-l border-white/8">
              <div className="pointer-events-none absolute inset-0 opacity-[0.14] [background-image:radial-gradient(circle_at_50%_44%,hsl(var(--primary)/0.16),transparent_30%),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.035)_1px,transparent_1px)] [background-size:100%_100%,34px_34px,34px_34px]" />
              <div className="relative flex h-full min-h-0 flex-col px-5 py-7">
                <div className="flex shrink-0 items-center justify-between gap-3">
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-primary/82">
                      GENERATOR LOADOUT
                    </div>
                    <h2 className="mt-2 text-lg font-semibold text-white">
                      一键配置生成
                    </h2>
                  </div>
                  {selectedTemplate ? (
                    <span className="flex size-9 items-center justify-center rounded-sm border border-primary/18 bg-primary/8 text-primary">
                      {selectedTemplate.icon}
                    </span>
                  ) : null}
                </div>

                <div className="mt-5 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.2)_transparent]">
                  <div className="rounded-sm border border-white/8 bg-black/10 p-3">
                    <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.14em] text-white/38">
                      ROLE
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {ROLE_PRESETS.map((preset) => {
                        const active = preset.id === selectedRolePresetId;
                        return (
                          <button
                            key={preset.id}
                            type="button"
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-[11px] leading-4 transition",
                              active
                                ? "border-[#f4e86f]/45 bg-[#f4e86f]/10 text-white"
                                : "border-white/10 bg-white/[0.025] text-white/52 hover:border-white/20 hover:text-white/82",
                            )}
                            onClick={() => setSelectedRolePresetId(preset.id)}
                          >
                            {preset.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="rounded-sm border border-white/8 bg-black/10 p-3">
                    <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.14em] text-white/38">
                      SCENE
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {SCENE_PRESETS.map((preset) => {
                        const active = selectedScenePresetIds.includes(
                          preset.id,
                        );
                        return (
                          <button
                            key={preset.id}
                            type="button"
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-[11px] leading-4 transition",
                              active
                                ? "border-[#f4e86f]/45 bg-[#f4e86f]/10 text-white"
                                : "border-white/10 bg-white/[0.025] text-white/52 hover:border-white/20 hover:text-white/82",
                            )}
                            onClick={() => toggleSelectedScenePreset(preset.id)}
                          >
                            {preset.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="rounded-sm border border-white/8 bg-black/10 p-3">
                    <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.14em] text-white/38">
                      CAPABILITY PACK
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {CAPABILITY_PACKS.map((pack) => {
                        const active = selectedCapabilityPackIds.includes(
                          pack.id,
                        );
                        return (
                          <button
                            key={pack.id}
                            type="button"
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-[11px] leading-4 transition",
                              active
                                ? "border-primary/45 bg-primary/10 text-white"
                                : "border-white/10 bg-white/[0.025] text-white/52 hover:border-white/20 hover:text-white/82",
                            )}
                            onClick={() =>
                              toggleSelectedCapabilityPack(pack.id)
                            }
                          >
                            {pack.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {selectedScenePresets.length > 0 &&
                  selectedCapabilityPacks.length > 0 ? (
                    <div className="grid gap-1.5 rounded-sm border border-white/8 bg-black/10 p-3 text-[11px] leading-5 text-white/48">
                      <div>
                        ARM:{" "}
                        <span className="text-white/72">
                          {selectedArms.join(", ")}
                        </span>
                      </div>
                      <div>
                        Skill:{" "}
                        <span className="text-white/72">
                          {selectedSkills.join(", ")}
                        </span>
                      </div>
                      <div>
                        权限:{" "}
                        <span className="text-white/72">
                          {selectedPermissions.join(" / ")}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  <Button
                    className="h-9 w-full rounded-sm bg-[#f4e86f] text-[#232323] hover:bg-[#fff27c]"
                    onClick={handleApplyGuidedConfig}
                  >
                    生成配置描述
                  </Button>

                  <div className="mt-1 rounded-sm border border-white/7 bg-white/[0.018] p-3">
                    <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.14em] text-white/32">
                      TEMPLATE REF
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {AGENT_TEMPLATES.map((template) => {
                        const active = template.id === selectedTemplateId;
                        return (
                          <button
                            key={template.id}
                            type="button"
                            className={cn(
                              "rounded-full border px-2 py-0.5 text-[10px] leading-4 transition",
                              active
                                ? "border-[#f4e86f]/30 bg-[#f4e86f]/8 text-white"
                                : "border-white/8 bg-black/12 text-white/40 hover:border-white/16 hover:text-white/72",
                            )}
                            onClick={() => handleSelectTemplate(template)}
                          >
                            {template.name}
                          </button>
                        );
                      })}
                    </div>
                    {selectedTemplate ? (
                      <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-white/34">
                        {selectedTemplate.description}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
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
                  <div className="flex flex-col items-center gap-4 rounded-lg border border-primary/20 bg-gradient-to-br from-primary/5 to-transparent py-8 text-center">
                    <div className="flex size-12 items-center justify-center rounded-md bg-primary/10">
                      <CheckCircleIcon className="text-primary h-6 w-6" />
                    </div>
                    <p className="font-semibold">{t.agents.agentCreated}</p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() =>
                          navigate(taskWorkspaceRoute({ agentId: agentName }))
                        }
                      >
                        {t.agents.startChatting}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => navigate(galleryReturnPath)}
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
