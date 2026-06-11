// ---------------------------------------------------------------------------
// Agent World Data Layer — extracted from agent-world-unified.tsx (2026-06)
//
// Pure data + type definitions + helper functions. No React, no UI. Keeping
// this file separate means:
//   1. Data mutations don't invalidate component memoization.
//   2. The root component file stays under the god-file threshold.
//   3. Data can be unit-tested independently.
// ---------------------------------------------------------------------------

import type { LucideIcon } from "lucide-react";
import {
  BotIcon,
  Code2Icon,
  Layers3Icon,
  LandmarkIcon,
  PaletteIcon,
  SearchCheckIcon,
  TargetIcon,
  WorkflowIcon,
} from "lucide-react";

import type {
  Agent,
  AgentWorldAgent,
  AgentWorldCategory,
} from "@/core/agents/types";

export type AgentCategoryFilter = "all" | AgentWorldCategory;
export type DigitalTwinStatus = "ready" | "draft" | "training";
export type DigitalTwinProfile = {
  id: string;
  name: string;
  role: string;
  description: string;
  sources: string;
  boundary: string;
  tone: string;
  status: DigitalTwinStatus;
  statusLabel: string;
  initials: string;
  icon: LucideIcon;
  accentClassName: string;
};
export type DigitalTwinRoleTier = "standard" | "expert";
export type DigitalTwinIndustry =
  | "all"
  | "operation"
  | "electronics"
  | "optics"
  | "communication"
  | "mechanical"
  | "reliability"
  | "software-ai"
  | "manufacturing"
  | "cross-domain";
export type DigitalTwinRoleTemplate = {
  id: string;
  index: number;
  name: string;
  focus: string;
  compound?: string;
};
export type DigitalTwinRoleGroup = {
  id: string;
  title: string;
  tier: DigitalTwinRoleTier;
  industry: Exclude<DigitalTwinIndustry, "all">;
  roles: DigitalTwinRoleTemplate[];
};

export const LOCAL_AGENT_ORDER = [
  "general",
  "coder",
  "vibe_selling",
  "ecommerce_mind",
  "market_researcher",
  "financial_earnings_reviewer",
  "desktop_operator",
  "admin",
] as const;
export const BUILTIN_LOCAL_AGENT_IDS = new Set<string>(LOCAL_AGENT_ORDER);
export const LOCAL_AGENT_RANK = new Map<string, number>(
  LOCAL_AGENT_ORDER.map((id, index) => [id, index]),
);
export const AGENT_CATEGORY_FILTERS: AgentCategoryFilter[] = [
  "all",
  "assistant",
  "coder",
  "researcher",
  "creative",
  "automation",
  "specialist",
  "financial",
];
export const CATEGORY_ICONS: Record<AgentCategoryFilter, LucideIcon> = {
  all: Layers3Icon,
  assistant: BotIcon,
  coder: Code2Icon,
  researcher: SearchCheckIcon,
  creative: PaletteIcon,
  automation: WorkflowIcon,
  specialist: TargetIcon,
  financial: LandmarkIcon,
};
export const DIGITAL_TWIN_STATUS_STYLES: Record<DigitalTwinStatus, string> = {
  ready:
    "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  draft:
    "border-slate-500/20 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  training:
    "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
};
export const DIGITAL_TWIN_INDUSTRY_FILTERS: DigitalTwinIndustry[] = [
  "all",
  "operation",
  "electronics",
  "optics",
  "communication",
  "mechanical",
  "reliability",
  "software-ai",
  "manufacturing",
  "cross-domain",
];
export const DIGITAL_TWIN_INDUSTRY_LABELS: Record<DigitalTwinIndustry, string> = {
  all: "全部",
  operation: "经营管理",
  electronics: "电子硬件",
  optics: "光学影像",
  communication: "通信射频",
  mechanical: "机械结构",
  reliability: "热声可靠性",
  "software-ai": "软件 AI",
  manufacturing: "制造供应链",
  "cross-domain": "跨域专家",
};
export const DIGITAL_TWIN_PROFILES: DigitalTwinProfile[] = [
  {
    id: "founder-twin",
    name: "创始人分身",
    role: "战略 / 决策 / 对外表达",
    description: "沉淀真实创始人的判断口径、产品原则和对外沟通风格。",
    sources: "访谈、会议纪要、公开材料",
    boundary: "重大承诺需本人确认",
    tone: "直接、克制、重结论",
    status: "draft",
    statusLabel: "草稿",
    initials: "创",
    icon: TargetIcon,
    accentClassName:
      "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  },
  {
    id: "product-twin",
    name: "产品分身",
    role: "需求 / PRD / 用户反馈",
    description: "沉淀产品负责人的需求判断、取舍原则和版本规划口径。",
    sources: "PRD、需求池、竞品、用户反馈",
    boundary: "路线图和优先级需本人确认",
    tone: "清晰、克制、重取舍",
    status: "draft",
    statusLabel: "草稿",
    initials: "产",
    icon: PaletteIcon,
    accentClassName:
      "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  {
    id: "project-twin",
    name: "项目分身",
    role: "排期 / 风险 / 跨部门推进",
    description: "沉淀项目负责人的节奏管理、风险台账和跨团队推进方式。",
    sources: "WBS、周报、会议纪要、风险台账",
    boundary: "资源冲突和延期承诺需本人确认",
    tone: "明确、稳妥、重闭环",
    status: "training",
    statusLabel: "训练中",
    initials: "项",
    icon: WorkflowIcon,
    accentClassName:
      "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
];
export const DIGITAL_TWIN_ROLE_GROUPS: DigitalTwinRoleGroup[] = [
  {
    id: "business-product-project",
    title: "经营 / 产品 / 项目岗",
    tier: "standard",
    industry: "operation",
    roles: [
      {
        id: "founder-owner",
        index: 1,
        name: "创始人 / 老板",
        focus: "公司控制塔、风险、现金流、关键待办",
      },
      {
        id: "business-assistant",
        index: 2,
        name: "经营助理 / 总经理助理",
        focus: "会议材料、催办、跨部门同步",
      },
      {
        id: "finance-manager",
        index: 3,
        name: "财务经理",
        focus: "预算、付款节点、费用异常、现金流预警",
      },
      {
        id: "legal-manager",
        index: 4,
        name: "法务经理",
        focus: "合同初审、条款风险、合规清单",
      },
      {
        id: "hr-recruiting-manager",
        index: 5,
        name: "HR / 招聘经理",
        focus: "JD、候选人对比、面试安排",
      },
      {
        id: "product-manager",
        index: 6,
        name: "产品经理",
        focus: "PRD、需求池、竞品、用户反馈",
      },
      {
        id: "hardware-product-manager",
        index: 7,
        name: "硬件产品经理",
        focus: "硬件规格、打样问题、BOM 关联",
      },
      {
        id: "ai-product-manager",
        index: 8,
        name: "AI 产品经理",
        focus: "Agent 流程、模型评估、Prompt 方案",
      },
      {
        id: "user-researcher",
        index: 9,
        name: "用户研究员",
        focus: "访谈提纲、反馈聚类、洞察摘要",
      },
      {
        id: "project-manager",
        index: 10,
        name: "项目经理",
        focus: "WBS、排期、周报、风险台账",
      },
      {
        id: "technical-program-manager",
        index: 11,
        name: "技术项目经理 / TPM",
        focus: "跨研发、供应链、制造里程碑推进",
      },
      {
        id: "pmo-manager",
        index: 12,
        name: "PMO 经理",
        focus: "多项目组合、资源冲突、延期统计",
      },
    ],
  },
  {
    id: "electronics-electrical-power",
    title: "电子 / 电气 / PCB / 电源岗",
    tier: "standard",
    industry: "electronics",
    roles: [
      {
        id: "hardware-engineer",
        index: 13,
        name: "硬件工程师",
        focus: "BOM、原理图检查、器件资料",
      },
      {
        id: "electronics-engineer",
        index: 14,
        name: "电子工程师",
        focus: "器件选型、参考设计、测试记录",
      },
      {
        id: "electrical-engineer",
        index: 15,
        name: "电气工程师",
        focus: "电气方案、接口定义、测试资料",
      },
      {
        id: "pcb-engineer",
        index: 16,
        name: "PCB 工程师",
        focus: "DFM/DRC checklist、布局规则",
      },
      {
        id: "pcb-layout-engineer",
        index: 17,
        name: "PCB Layout 工程师",
        focus: "走线规则、阻抗规则、生产文件检查",
      },
      {
        id: "power-engineer",
        index: 18,
        name: "电源工程师",
        focus: "电源树、功耗、充电方案、电源风险",
      },
      {
        id: "battery-engineer",
        index: 19,
        name: "电池工程师",
        focus: "电池规格、保护方案、容量估算",
      },
      {
        id: "connector-engineer",
        index: 20,
        name: "连接器工程师",
        focus: "接口选型、插拔寿命、供应商资料",
      },
      {
        id: "signal-integrity-engineer",
        index: 21,
        name: "信号完整性工程师 / SI",
        focus: "高速信号、阻抗、仿真资料",
      },
      {
        id: "power-integrity-engineer",
        index: 22,
        name: "电源完整性工程师 / PI",
        focus: "供电网络、噪声、仿真记录",
      },
      {
        id: "emc-emi-engineer",
        index: 23,
        name: "EMC/EMI 工程师",
        focus: "EMC 风险、整改记录、测试报告",
      },
      {
        id: "hardware-system-engineer",
        index: 24,
        name: "硬件系统工程师",
        focus: "模块架构、接口关系、系统风险",
      },
      {
        id: "hardware-test-engineer",
        index: 25,
        name: "硬件测试工程师",
        focus: "样机测试、测试数据、问题复现",
      },
      {
        id: "hardware-technician",
        index: 26,
        name: "硬件技术员",
        focus: "焊接、改板、样机维护、测试记录",
      },
    ],
  },
  {
    id: "optics-imaging-sensor",
    title: "光 / 光机 / 显示 / 传感岗",
    tier: "standard",
    industry: "optics",
    roles: [
      {
        id: "optical-engineer",
        index: 27,
        name: "光学工程师",
        focus: "镜头、传感器参数、光学测试资料",
      },
      {
        id: "opto-mechanical-engineer",
        index: 28,
        name: "光机工程师",
        focus: "光机结构、公差、装调 checklist",
      },
      {
        id: "display-engineer",
        index: 29,
        name: "显示工程师",
        focus: "屏幕模组、显示参数、测试数据",
      },
      {
        id: "camera-engineer",
        index: 30,
        name: "摄像头工程师",
        focus: "Camera module、ISP 问题、图像测试",
      },
      {
        id: "vision-engineer",
        index: 31,
        name: "视觉工程师",
        focus: "图像质量、视觉算法评估资料",
      },
      {
        id: "image-quality-engineer",
        index: 32,
        name: "图像质量工程师 / IQ Engineer",
        focus: "样张对比、画质问题分类",
      },
      {
        id: "sensor-engineer",
        index: 33,
        name: "传感器工程师",
        focus: "传感器选型、标定文档、精度对比",
      },
      {
        id: "touch-engineer",
        index: 34,
        name: "触控工程师",
        focus: "触控模组、灵敏度、测试问题",
      },
      {
        id: "lidar-tof-engineer",
        index: 35,
        name: "激光/雷达工程师",
        focus: "LiDAR/ToF 参数、测试数据",
      },
      {
        id: "optoelectronic-engineer",
        index: 36,
        name: "光电工程师",
        focus: "光电器件、信号链、测试报告",
      },
      {
        id: "infrared-engineer",
        index: 37,
        name: "红外工程师",
        focus: "红外传感、热成像、测试资料",
      },
      {
        id: "display-test-engineer",
        index: 38,
        name: "显示测试工程师",
        focus: "屏幕亮度、色彩、均匀性测试记录",
      },
    ],
  },
  {
    id: "rf-communication-antenna",
    title: "射频 / 通信 / 天线岗",
    tier: "standard",
    industry: "communication",
    roles: [
      {
        id: "rf-engineer",
        index: 39,
        name: "射频工程师 / RF Engineer",
        focus: "RF 测试、天线资料、认证问题",
      },
      {
        id: "antenna-engineer",
        index: 40,
        name: "天线工程师",
        focus: "天线方案、测试数据、调试记录",
      },
      {
        id: "wireless-communication-engineer",
        index: 41,
        name: "无线通信工程师",
        focus: "蓝牙/Wi-Fi/蜂窝连接问题整理",
      },
      {
        id: "bluetooth-engineer",
        index: 42,
        name: "蓝牙工程师",
        focus: "BLE 协议、连接日志、兼容性问题",
      },
      {
        id: "wifi-engineer",
        index: 43,
        name: "Wi-Fi 工程师",
        focus: "网络测试、吞吐、掉线问题归类",
      },
      {
        id: "cellular-engineer",
        index: 44,
        name: "蜂窝通信工程师",
        focus: "LTE/5G 模块、认证、网络兼容性",
      },
      {
        id: "gnss-gps-engineer",
        index: 45,
        name: "GNSS/GPS 工程师",
        focus: "定位精度、天线、测试轨迹分析",
      },
      {
        id: "communication-protocol-engineer",
        index: 46,
        name: "通信协议工程师",
        focus: "协议栈、接口文档、问题复盘",
      },
    ],
  },
  {
    id: "mechanical-structure-industrial",
    title: "机械 / 结构 / 工业设计 / 包装岗",
    tier: "standard",
    industry: "mechanical",
    roles: [
      {
        id: "mechanical-engineer",
        index: 47,
        name: "机械工程师",
        focus: "结构需求、装配问题、供应商修改点",
      },
      {
        id: "structural-engineer",
        index: 48,
        name: "结构工程师",
        focus: "3D 结构说明、开模问题、装配约束",
      },
      {
        id: "product-design-engineer",
        index: 49,
        name: "产品设计工程师",
        focus: "产品架构、结构方案、量产问题追踪",
      },
      {
        id: "industrial-designer",
        index: 50,
        name: "工业设计师",
        focus: "外观概念、CMF、竞品外观分析",
      },
      {
        id: "cmf-designer",
        index: 51,
        name: "CMF 设计师",
        focus: "颜色、材料、工艺方案整理",
      },
      {
        id: "packaging-engineer",
        index: 52,
        name: "包装工程师",
        focus: "包装结构、运输测试、包装 BOM",
      },
      {
        id: "materials-engineer",
        index: 53,
        name: "材料工程师",
        focus: "材料对比、供应商资料、失效记录",
      },
      {
        id: "tooling-engineer",
        index: 54,
        name: "模具工程师",
        focus: "开模问题、模具修改、试模记录",
      },
      {
        id: "injection-molding-engineer",
        index: 55,
        name: "注塑工程师",
        focus: "注塑参数、缺陷归类、工艺记录",
      },
      {
        id: "sheet-metal-engineer",
        index: 56,
        name: "钣金工程师",
        focus: "钣金结构、加工约束、供应商反馈",
      },
      {
        id: "cae-engineer",
        index: 57,
        name: "CAE 工程师",
        focus: "仿真流程、结果整理、测试对比",
      },
      {
        id: "prototype-engineer",
        index: 58,
        name: "样机工程师 / Prototype Engineer",
        focus: "样机制作、改版记录、问题追踪",
      },
    ],
  },
  {
    id: "thermal-acoustic-reliability-test",
    title: "热 / 声 / 可靠性 / 测试岗",
    tier: "standard",
    industry: "reliability",
    roles: [
      {
        id: "thermal-design-engineer",
        index: 59,
        name: "热设计工程师",
        focus: "温升数据、散热方案、热仿真资料",
      },
      {
        id: "thermal-simulation-engineer",
        index: 60,
        name: "热仿真工程师",
        focus: "CFD/热仿真流程、结果对比",
      },
      {
        id: "thermal-test-engineer",
        index: 61,
        name: "热测试工程师",
        focus: "热测试计划、数据整理、报告",
      },
      {
        id: "acoustic-engineer",
        index: 62,
        name: "声学工程师",
        focus: "麦克风/扬声器参数、声学测试报告",
      },
      {
        id: "audio-engineer",
        index: 63,
        name: "音频工程师",
        focus: "音频链路、调音记录、测试问题",
      },
      {
        id: "vibration-engineer",
        index: 64,
        name: "振动工程师",
        focus: "振动测试、结构噪声、异常记录",
      },
      {
        id: "reliability-engineer",
        index: 65,
        name: "可靠性工程师",
        focus: "老化、跌落、温湿度测试计划",
      },
      {
        id: "test-engineer",
        index: 66,
        name: "测试工程师",
        focus: "测试用例、测试数据、问题复现",
      },
      {
        id: "failure-analysis-engineer",
        index: 67,
        name: "失效分析工程师 / FA",
        focus: "根因分析、批次关联、FA 报告",
      },
      {
        id: "product-integrity-engineer",
        index: 68,
        name: "产品完整性工程师",
        focus: "可靠性、质量、制造放行材料",
      },
    ],
  },
  {
    id: "embedded-firmware-software-algorithm",
    title: "嵌入式 / 固件 / 软件 / 算法岗",
    tier: "standard",
    industry: "software-ai",
    roles: [
      {
        id: "embedded-software-engineer",
        index: 69,
        name: "嵌入式软件工程师",
        focus: "驱动、日志、接口文档、bug 复盘",
      },
      {
        id: "firmware-engineer",
        index: 70,
        name: "固件工程师",
        focus: "固件版本、烧录流程、发布记录",
      },
      {
        id: "bsp-engineer",
        index: 71,
        name: "BSP 工程师",
        focus: "板级支持包、启动日志、驱动适配",
      },
      {
        id: "linux-driver-engineer",
        index: 72,
        name: "Linux 驱动工程师",
        focus: "驱动代码、内核日志、接口说明",
      },
      {
        id: "android-system-engineer",
        index: 73,
        name: "Android 系统工程师",
        focus: "系统定制、兼容性、日志分析",
      },
      {
        id: "ai-engineer",
        index: 74,
        name: "AI 工程师",
        focus: "RAG、Agent、模型评估、数据记录",
      },
      {
        id: "algorithm-engineer",
        index: 75,
        name: "算法工程师",
        focus: "实验记录、评估报告、数据分析",
      },
      {
        id: "machine-vision-algorithm-engineer",
        index: 76,
        name: "机器视觉算法工程师",
        focus: "视觉模型、样本、评估指标",
      },
    ],
  },
  {
    id: "manufacturing-quality-supply-chain",
    title: "制造 / 质量 / 供应链岗",
    tier: "standard",
    industry: "manufacturing",
    roles: [
      {
        id: "manufacturing-engineer",
        index: 77,
        name: "制造工程师",
        focus: "工艺流程、产线问题、良率改善",
      },
      {
        id: "quality-engineer",
        index: 78,
        name: "质量工程师",
        focus: "缺陷归类、质量报告、8D 草稿",
      },
      {
        id: "supply-chain-manager",
        index: 79,
        name: "供应链经理",
        focus: "供应商状态、交期、风险、替代料",
      },
      {
        id: "procurement-manager-buyer",
        index: 80,
        name: "采购经理 / Buyer",
        focus: "RFQ、比价、催交、采购单草稿",
      },
    ],
  },
  {
    id: "compound-experts",
    title: "复合专家岗",
    tier: "expert",
    industry: "cross-domain",
    roles: [
      {
        id: "opto-mechanical-system-expert",
        index: 1,
        name: "光机系统专家",
        compound: "光学 + 机械 + 公差 + 装调",
        focus: "光路与结构约束、装调 checklist、风险清单",
      },
      {
        id: "mechatronics-expert",
        index: 2,
        name: "机电一体化专家",
        compound: "机械 + 电控 + 传感器 + 运动控制",
        focus: "联调问题、接口关系、运动机构风险",
      },
      {
        id: "thermal-structure-expert",
        index: 3,
        name: "热-结构联合专家",
        compound: "热设计 + 结构 + 材料 + 可靠性",
        focus: "散热路径、结构约束、温升数据关联",
      },
      {
        id: "acoustic-structure-expert",
        index: 4,
        name: "声学-结构专家",
        compound: "声学 + 结构 + 材料 + 调音",
        focus: "声腔、振动、材料、测试记录联动",
      },
      {
        id: "rf-structure-expert",
        index: 5,
        name: "射频-结构专家",
        compound: "RF + 天线 + 结构 + 材料",
        focus: "天线位置、外壳材料、认证风险",
      },
      {
        id: "power-thermal-expert",
        index: 6,
        name: "电源-热专家",
        compound: "电源 + 功耗 + 热 + 安规",
        focus: "电源树、功耗预算、温升与安全风险",
      },
      {
        id: "hardware-system-architect",
        index: 7,
        name: "硬件系统架构专家",
        compound: "硬件 + 电源 + 接口 + 可靠性",
        focus: "系统框图、模块依赖、风险分解",
      },
      {
        id: "embedded-hardware-debug-expert",
        index: 8,
        name: "嵌入式-硬件联调专家",
        compound: "嵌入式 + 硬件 + 调试 + 测试",
        focus: "bring-up 记录、问题归因、接口验证",
      },
      {
        id: "robotics-system-expert",
        index: 9,
        name: "机器人系统专家",
        compound: "机械 + 电控 + 传感器 + 算法",
        focus: "运动控制、传感融合、现场调试记录",
      },
      {
        id: "smart-hardware-product-architect",
        index: 10,
        name: "智能硬件产品架构专家",
        compound: "产品 + 硬件 + 软件 + 供应链",
        focus: "产品定义、功能取舍、成本/交期影响",
      },
      {
        id: "npi-ramp-expert",
        index: 11,
        name: "NPI 量产导入专家",
        compound: "工程 + 制造 + 质量 + 供应链",
        focus: "试产问题、齐套、良率、变更追踪",
      },
      {
        id: "dfm-dfx-expert",
        index: 12,
        name: "DFM/DFx 专家",
        compound: "设计 + 制造 + 测试 + 可靠性",
        focus: "可制造性、可测试性、可维护性检查",
      },
      {
        id: "supply-chain-engineering-expert",
        index: 13,
        name: "供应链工程专家",
        compound: "供应链 + 工程 + BOM + 替代料",
        focus: "缺料风险、替代料、成本与工程影响",
      },
      {
        id: "supplier-quality-expert",
        index: 14,
        name: "供应商质量专家",
        compound: "SQE + 质量 + 工艺 + 供应商管理",
        focus: "供应商 8D、来料异常、审核资料",
      },
      {
        id: "hardware-quality-closed-loop-expert",
        index: 15,
        name: "硬件质量闭环专家",
        compound: "测试 + 质量 + 可靠性 + 售后",
        focus: "缺陷趋势、批次关联、质量闭环",
      },
      {
        id: "product-compliance-certification-expert",
        index: 16,
        name: "产品合规认证专家",
        compound: "法规 + 硬件 + RF + 安规",
        focus: "CE/FCC/ROHS/电池等认证资料与风险",
      },
      {
        id: "factory-delivery-expert",
        index: 17,
        name: "工厂交付专家",
        compound: "制造 + 计划 + 质量 + 物流",
        focus: "排产、交付、工厂异常、验收资料",
      },
      {
        id: "ai-hardware-system-expert",
        index: 18,
        name: "AI 硬件系统专家",
        compound: "AI + 嵌入式 + 传感器 + 云端",
        focus: "端侧模型、数据链路、设备云、评估",
      },
      {
        id: "smart-manufacturing-automation-expert",
        index: 19,
        name: "智能制造自动化专家",
        compound: "自动化 + 设备 + 工艺 + 数据",
        focus: "产线自动化、设备数据、良率分析",
      },
      {
        id: "presales-solution-expert",
        index: 20,
        name: "售前解决方案专家",
        compound: "产品 + 技术 + 客户 + 交付",
        focus: "客户方案、演示材料、需求到交付闭环",
      },
    ],
  },
];

export function localAgentToWorldAgent(agent: Agent): AgentWorldAgent {
  const displayName = agent.display_name ?? agent.name;
  const toolGroups = agent.tool_groups ?? [];
  return {
    id: agent.name,
    name: agent.name,
    display_name: displayName,
    description: agent.description || `${displayName} Agent`,
    author: "Octopus",
    category: toolGroups.length > 0 ? "automation" : "assistant",
    tags: toolGroups,
    icon: agent.icon || "🤖",
    avatar_url: agent.avatar_url ?? undefined,
    visual_urls: agent.visual_urls ?? undefined,
    version: "1.0.0",
    downloads: 0,
    rating: 4.8,
    rating_count: Math.max(1, toolGroups.length),
    is_featured: false,
    is_official: true,
    is_installed: true,
    created_at: new Date().toISOString(),
  };
}

export function worldAgentToAgent(agent: AgentWorldAgent): Agent {
  return {
    name: agent.id,
    display_name: agent.display_name,
    description: agent.description,
    icon: agent.icon,
    avatar_url: agent.avatar_url ?? null,
    visual_urls: agent.visual_urls ?? null,
    model: null,
    tool_groups: agent.tags,
  };
}
