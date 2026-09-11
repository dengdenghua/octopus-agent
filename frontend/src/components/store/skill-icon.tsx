import {
  AudioLines,
  BookOpen,
  Bot,
  ChartNoAxesCombined,
  Clapperboard,
  CodeXml,
  Database,
  FileText,
  Globe,
  GraduationCap,
  Image,
  Mail,
  Megaphone,
  Palette,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Terminal,
  Workflow,
  type LucideIcon,
} from "lucide-react";

const tones = {
  violet:
    "bg-violet-100/80 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300",
  blue: "bg-blue-100/80 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300",
  teal: "bg-teal-100/80 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
  amber:
    "bg-amber-100/80 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  rose: "bg-rose-100/80 text-rose-600 dark:bg-rose-500/15 dark:text-rose-300",
};

// Match the skill's identity first; broad catalog tags are only a fallback.
const families: {
  match: RegExp;
  icon: LucideIcon;
  tone: keyof typeof tones;
}[] = [
  { match: /email|imap|smtp|mail|邮件|邮箱/, icon: Mail, tone: "blue" },
  {
    match: /security|safety|vuln|legal|contract|安全|法律|合同/,
    icon: ShieldCheck,
    tone: "teal",
  },
  {
    match:
      /audio|voice|speech|tts|podcast|music|score|dubbing|lip|音频|音乐|配音/,
    icon: AudioLines,
    tone: "rose",
  },
  {
    match:
      /video|film|cinema|anime|animation|storyboard|drama|motion|comfy|剪辑|影视|动画|短剧|动效/,
    icon: Clapperboard,
    tone: "violet",
  },
  {
    match: /image|photo|inpaint|render|poster|pixel|seedream|图片|海报/,
    icon: Image,
    tone: "rose",
  },
  { match: /database|sql|数据库/, icon: Database, tone: "teal" },
  {
    match:
      /data|chart|stat|hypothesis|finance|equity|stock|sizing|okr|分析|统计|金融/,
    icon: ChartNoAxesCombined,
    tone: "teal",
  },
  {
    match: /browser|browse|scrap|playwright|seo|浏览|爬虫/,
    icon: Globe,
    tone: "blue",
  },
  {
    match: /research|paper|science|学术|论文|研究/,
    icon: BookOpen,
    tone: "blue",
  },
  {
    match: /education|course|tutor|mentor|interview|教育|课程|面试/,
    icon: GraduationCap,
    tone: "amber",
  },
  {
    match: /design|visual|(?:^|-)ui(?:-|$)|brand|palette|设计|视觉/,
    icon: Palette,
    tone: "violet",
  },
  {
    match: /ad-|marketing|copywriter|pricing|cro-|广告|营销/,
    icon: Megaphone,
    tone: "amber",
  },
  { match: /agent|bot|swarm|智能体/, icon: Bot, tone: "violet" },
  {
    match: /devops|k8s|kubectl|terraform|deploy|cli|terminal|部署|运维/,
    icon: Terminal,
    tone: "blue",
  },
  {
    match:
      /code|api|frontend|backend|fullstack|full-stack|typescript|tdd|test|git|编程|开发/,
    icon: CodeXml,
    tone: "blue",
  },
  {
    match: /audit|diagnostic|inspect|probe|审计|诊断/,
    icon: ScanSearch,
    tone: "teal",
  },
  {
    match: /writing|writer|report|doc|pdf|resume|content|prose|文档|写作|报告/,
    icon: FileText,
    tone: "amber",
  },
  {
    match: /workflow|pipeline|automation|integration|工作流|自动化/,
    icon: Workflow,
    tone: "violet",
  },
];

export function SkillIcon({
  name,
  tags = [],
}: {
  name: string;
  tags?: string[];
}) {
  const identity = name.toLowerCase().replace(/[_\s]+/g, "-");
  const family =
    families.find(({ match }) => match.test(identity)) ??
    families.find(({ match }) => match.test(tags.join(" ").toLowerCase()));
  const Icon = family?.icon ?? Sparkles;
  return (
    <span
      aria-hidden="true"
      className={`grid size-10 shrink-0 place-items-center rounded-xl ${tones[family?.tone ?? "violet"]}`}
    >
      <Icon className="size-5" strokeWidth={1.7} />
    </span>
  );
}
