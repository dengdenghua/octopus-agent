export type ToolActionKind =
  | "search"
  | "read"
  | "call"
  | "skill"
  | "create"
  | "write"
  | "edit"
  | "list"
  | "run"
  | "browse"
  | "fetch"
  | "update"
  | "learn"
  | "plan"
  | "other";

export type ToolActionStatus =
  | "running"
  | "done"
  | "error"
  | "waiting_approval";

export function isChineseText(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text);
}

export function isSkillToolName(name: string): boolean {
  const normalized = name.toLowerCase();
  return (
    normalized === "apply_skill" ||
    normalized === "list_learned_skills" ||
    normalized === "learn_skill_from_text" ||
    normalized === "deep-research-swarm" ||
    normalized === "deep-research" ||
    normalized === "report-writing" ||
    normalized === "docx" ||
    normalized === "pptx-swarm" ||
    normalized === "webapp-building-swarm" ||
    normalized === "skill_search" ||
    normalized === "install_skill" ||
    normalized.includes("skill")
  );
}

export function inferToolActionKind(
  name: string,
  args: Record<string, unknown> = {},
): ToolActionKind {
  const normalized = name.toLowerCase();
  if (
    normalized.includes("planning") ||
    normalized === "plan" ||
    normalized === "planning"
  ) {
    return "plan";
  }
  if (isSkillToolName(normalized)) {
    return normalized.includes("learn") ? "learn" : "skill";
  }
  if (
    normalized === "web_search" ||
    normalized === "image_search" ||
    normalized.includes("search") ||
    normalized.includes("grep") ||
    normalized.includes("glob")
  ) {
    return "search";
  }
  if (normalized === "web_fetch" || normalized.includes("fetch")) {
    return "fetch";
  }
  if (
    normalized === "ls" ||
    normalized === "list_cwd" ||
    normalized.includes("list") ||
    normalized.includes("cwd")
  ) {
    return "list";
  }
  if (
    normalized === "read_file" ||
    normalized === "read_file_range" ||
    normalized === "read_text_file" ||
    normalized.includes("read") ||
    normalized.includes("view")
  ) {
    return "read";
  }
  if (
    normalized.includes("edit") ||
    normalized.includes("replace") ||
    normalized === "str_replace"
  ) {
    return "edit";
  }
  if (normalized.includes("create") || normalized.includes("new_file")) {
    return "create";
  }
  if (normalized.includes("write") || normalized.includes("append")) {
    return "write";
  }
  if (
    normalized === "bash" ||
    normalized === "exec_shell" ||
    normalized === "mcp_exec_shell" ||
    normalized === "shell_command" ||
    normalized.includes("run") ||
    normalized.includes("shell") ||
    normalized.includes("exec")
  ) {
    return "run";
  }
  if (normalized.includes("browse") || normalized.includes("url")) {
    return "browse";
  }
  if (normalized.includes("update") || normalized.includes("todo")) {
    return "update";
  }
  if (normalized.includes("agent") || normalized.includes("call_")) {
    return "call";
  }
  if (Object.keys(args).length > 0 && "query" in args) {
    return "search";
  }
  return "call";
}

export function inferToolActionKindFromText(text: string): ToolActionKind {
  const trimmed = text.trim();
  const actionMatch = /^Action:\s*([A-Za-z0-9_-]+)/i.exec(trimmed);
  if (actionMatch?.[1]) {
    return inferToolActionKind(actionMatch[1], {});
  }
  if (/搜索|查找|search/i.test(trimmed)) return "search";
  if (/web_fetch|fetch_url|\bfetch\b/i.test(trimmed)) return "fetch";
  if (/读取|read|查看|浏览/i.test(trimmed)) return "read";
  if (/技能|skill/i.test(trimmed)) return "skill";
  if (/创建|create|new file|生成文件/i.test(trimmed)) return "create";
  if (/写入|write|append/i.test(trimmed)) return "write";
  if (/编辑|edit|替换|replace/i.test(trimmed)) return "edit";
  if (/列出|list/i.test(trimmed)) return "list";
  if (/执行|run|bash|shell/i.test(trimmed)) return "run";
  if (/调用|call|invoke/i.test(trimmed)) return "call";
  if (
    /\u89c4\u5212|\u4e0b\u4e00\u6b65|\bplanning\b|\bplan next\b|\bmake a plan\b/i.test(
      trimmed,
    )
  )
    return "plan";
  return "other";
}

export function isRunningStatus(status: ToolActionStatus | boolean): boolean {
  return (
    status === true || status === "running" || status === "waiting_approval"
  );
}

export function actionStateLabel(
  kind: ToolActionKind,
  status: ToolActionStatus | boolean,
  languageProbe: string,
): string {
  const zh = isChineseText(languageProbe);
  const zhLabels: Record<ToolActionKind, [string, string]> = {
    search: ["正在搜索", "已搜索"],
    read: ["正在读取", "已读取"],
    call: ["正在调用", "已调用"],
    skill: ["正在应用技能", "已应用技能"],
    create: ["正在创建文件", "已创建文件"],
    write: ["正在写入文件", "已写入文件"],
    edit: ["正在编辑文件", "已编辑文件"],
    list: ["正在浏览目录", "已浏览目录"],
    run: ["正在运行命令", "已运行命令"],
    browse: ["正在浏览网页", "已浏览网页"],
    fetch: ["正在获取网页", "已获取网页"],
    update: ["正在更新", "已更新"],
    learn: ["正在学习技能", "已学习技能"],
    plan: ["正在规划下一步", "已规划下一步"],
    other: ["正在执行", "已执行"],
  };
  const enLabels: Record<ToolActionKind, [string, string]> = {
    search: ["Searching", "Searched"],
    read: ["Reading", "Read"],
    call: ["Calling", "Called"],
    skill: ["Applying skill", "Applied skill"],
    create: ["Creating file", "Created file"],
    write: ["Writing file", "Wrote file"],
    edit: ["Editing file", "Edited file"],
    list: ["Browsing directory", "Browsed directory"],
    run: ["Running command", "Ran command"],
    browse: ["Browsing web", "Browsed web"],
    fetch: ["Fetching page", "Fetched page"],
    update: ["Updating", "Updated"],
    learn: ["Learning skill", "Learned skill"],
    plan: ["Planning next step", "Planned next step"],
    other: ["Executing", "Executed"],
  };
  const [running, done] = zh ? zhLabels[kind] : enLabels[kind];
  return isRunningStatus(status) ? running : done;
}

export function actionLabelWithTarget(
  kind: ToolActionKind,
  status: ToolActionStatus | boolean,
  languageProbe: string,
  target?: string,
): string {
  const label = actionStateLabel(kind, status, languageProbe);
  return target ? `${label} ${target}` : label;
}

export function reasoningStateLabel(
  summary: string,
  active: boolean,
  languageProbe: string,
): string {
  const zh = isChineseText(languageProbe);
  const planning = /规划|下一步|plan/i.test(summary);
  if (zh) {
    if (planning) return active ? "正在规划下一步" : "已规划下一步";
    return active ? "思考中" : "思考";
  }
  if (planning) return active ? "Planning next step" : "Planned next step";
  return active ? "Thinking" : "Thought";
}
