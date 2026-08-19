---
name: dcs-cloud
display_name: DCS Cloud生命科学研究智能平台
display_name_en: DCS Cloud Intelligent Platform for Life-Science Research
description: Operate DCS Cloud via MCP tools — projects, offline analysis tasks, WDL workflows, billing groups, and data files. Use when the user mentions DCS Cloud, projects, tasks, workflows, billing, or data files.
description_zh: 通过 MCP 工具操作 DCS Cloud：项目、离线分析任务、WDL 工作流、计费组、数据文件。用户提到 华大、DCS、云平台、项目、任务、workflow、计费、数据文件时使用。
category: bioinformatics
version: 1.0.1
author: DCS Genpilot
---

# DCS Cloud MCP 工具

本连接器通过 **MCP 协议** 暴露 20 个工具，操作 DCS Cloud 的项目、个性化分析任务、WDL 工作流、计费组与数据文件。AI 应通过调用这些 MCP 工具完成操作，**不要**尝试直接运行 `dcs` shell 命令（MCP 运行环境下无法 spawn 子进程，且本连接器已将所需能力封装为工具）。

## 鉴权说明

- 用户需在 [https://www.dcs.cloud/](https://www.dcs.cloud/) 个人资料页创建 PAT（`dcs_pat_` 开头），填入 WorkBuddy 连接器表单。
- MCP Server 启动时通过 `DCS_PAT` 环境变量接收 PAT，并传给 `dcs` CLI 完成登录。**PAT 不会出现在进程参数中**，AI 也不应、无需在对话中接触 PAT。
- 首次调用工具时 Server 自动完成登录；后续调用复用登录态。
- 若用户未配置 PAT，工具调用会返回 `DCS_PAT is not set` 错误，应提示用户去 WorkBuddy 表单填写。

## 工具列表

### list_projects
列出当前用户可见的全部项目。

- **入参**：无
- **返回**：项目列表 JSON

### current_project
查看当前选中的项目。

- **入参**：无
- **返回**：当前项目信息 JSON

### switch_project
切换当前项目（`id` 与 `name` 二选一，`id` 优先）。

- **入参**：
  - `id` (string, 可选)：项目 code，如 `PRJ-123`
  - `name` (string, 可选)：项目名（精确匹配）
- **注意**：切换项目后，后续工具调用将作用于新项目。

### list_tasks
列出当前项目的离线任务（个性化分析 shell 任务，非 WDL workflow）。

- **入参**：无
- **返回**：任务列表 JSON

### task_info
查看任务详情（子任务、notebook、日志摘要）。

- **入参**：`task_id` (string, **必填**)

### task_log
查看任务运行日志。

- **入参**：`task_id` (string, **必填**)

### cancel_task
取消任务；批量取消多个任务时用逗号分隔 ID。

- **入参**：`task_id` (string, **必填**)
- **建议**：取消前先用 `task_info` 确认任务状态，避免误取消已完成任务。

### list_data
浏览当前项目数据目录下的文件/子目录。

- **入参**：
  - `path` (string, 可选)：路径，如 `/Files/datasets`；省略则列当前数据目录
  - `long` (boolean, 可选)：详细模式（含大小、时间、创建者）
  - `page` (integer, 可选)：页码，默认 1
  - `page_size` (integer, 可选)：每页条数，最大 200，默认 20
- **路径规则**：以 `/` 开头的绝对路径原样使用；相对路径基于当前数据目录解析。

## 计费组工具

### list_billing_groups
列出当前用户有权限的计费组，支持按名称模糊搜索。

- **入参**：
  - `name` (string, 可选)：计费组名称模糊搜索关键词

## WDL 工作流工具

以下工具操作 **WDL 工作流任务**（通过 `dcs workflow` 命令）。与 `list_tasks`/`task_info`/`task_log`/`cancel_task`（个性化分析 shell 任务，通过 `dcs analysis` 命令）是不同类型的，请勿混淆。

### list_workflows
列出 WDL 工作流。

- **入参**（均可选）：
  - `name` (string)：按流程名模糊筛选
  - `public` (boolean)：查询公共库
  - `tag` (string)：按标签筛选（多个用逗号分隔）
  - `user` (string)：按创建者模糊筛选
  - `page` / `page_size` (integer)：分页
  - `all` (boolean)：自动分页查询全部

### workflow_info
查看 WDL 工作流详情。

- **入参**：
  - `name` (string, **必填**)：工作流名称
  - `version` (string, 可选)：版本，默认最新
  - `public` (boolean, 可选)：从公共库查询

### workflow_check_parameter
查看 WDL 工作流的输入参数规格（必填/可选、类型、默认值、说明）。

- **入参**：
  - `name` (string, **必填**)：工作流名称
  - `version` (string, 可选)：版本，默认最新

### workflow_plan
根据一组 WDL 名称生成多步执行规划，并验证每个流程是否存在。

- **入参**：
  - `names` (array, **必填**)：WDL 工作流名称列表（按执行顺序，至少一个）
  - `version` (string, 可选)：应用于每步的版本

### run_workflow
投递一个 WDL 工作流任务。以 `key=value` 字符串数组传参。

- **入参**：
  - `name` (string, **必填**)：工作流名称
  - `version` (string, 可选)：版本
  - `entity` (string, 可选)：实体/样本 ID
  - `inputs` (array, 可选)：任务输入，`key=value` 字符串数组
  - `output_path` (string, 可选)：输出路径，如 `/Files/Result/...`
- **限制**：文件方式传参（`-j` JSON 文件 / `--table` 表格文件）未通过 MCP 暴露，需文件传参时请提示用户直接用 dcs CLI。

### list_workflow_tasks
列出当前项目已投递的 WDL 工作流任务。

- **入参**（均可选）：
  - `name` / `id` / `status` / `entity` / `user` (string)：筛选条件
  - `time` (string)：时间范围，格式 `YYYY-MM-DD~YYYY-MM-DD`
  - `page` / `page_size` (integer)：分页
  - `all` (boolean)：自动分页查询全部

### workflow_task_info
查看 WDL 工作流任务详情（提交信息、输入输出、运行日志）。

- **入参**：`task_id` (string, **必填**)

### workflow_task_log
查看 WDL 工作流任务运行日志。用 `step_name` 配合 `stdout`/`stderr`/`script` 查看指定步骤输出。

- **入参**：
  - `task_id` (string, **必填**)
  - `step_name` (string, 可选)：步骤名（格式 `stepName` 或 `stepName-shardNo`）
  - `stdout` / `stderr` / `script` / `intermediate` (boolean, 可选)：查看步骤的 stdout/stderr/脚本/中间文件

### start_workflow_task
启动 WDL 工作流任务。批量用逗号分隔多个 ID。

- **入参**：`task_id` (string, **必填**)

### cancel_workflow_task
取消 WDL 工作流任务。批量用逗号分隔多个 ID。

- **入参**：`task_id` (string, **必填**)
- **建议**：取消前先用 `workflow_task_info` 确认任务状态。

### remove_workflow_task
删除 WDL 工作流任务。批量用逗号分隔多个 ID。

- **入参**：`task_id` (string, **必填**)

## 常见错误码

| 码 | 含义 | 处理 |
|----|------|------|
| 83002 / 70102 / 41104 | 未登录 | 提示用户在 WorkBuddy 表单重新填写 PAT |
| 83003 / 41102 | 未选项目 | 调用 `switch_project` |
| 83011 | `user_id` 无效/非数值 | 提示用户重新填写 PAT 重新登录 |
| 超时 | 子进程 30s 未响应 | 建议用户稍后重试，或缩小查询范围（如分页） |

## 使用约定

- **输出格式**：所有工具返回 JSON，无需指定 `--output`。
- **任务 ID**：直接传字符串，不要带尖括号 `<...>`。
- **路径**：数据浏览用 `/Files/...` 绝对路径。
- **批量操作**：多个 `task_id` 用英文逗号 `,` 分隔，作为一个字符串传入（适用于 `cancel_task`、`start_workflow_task`、`cancel_workflow_task`、`remove_workflow_task`）。
- **两类任务区分**：`list_tasks`/`task_info`/`task_log`/`cancel_task` 是**个性化分析任务**（`dcs analysis`）；`list_workflow_tasks`/`workflow_task_info`/`workflow_task_log`/`cancel_workflow_task` 是 **WDL 工作流任务**（`dcs workflow`）。请勿混淆。

## 能力边界

本连接器暴露 20 个 MCP 工具，覆盖项目、个性化分析任务、WDL 工作流、计费组、数据浏览。以下 dcs CLI 能力**未封装为 MCP 工具**，AI 无法通过本连接器执行，应告知用户当前暂不支持：

| 未暴露的能力 | dcs CLI 命令 | 原因 |
|---|---|---|
| 下载文件到本机 | `dcs data download` | 需用户本机目录作为 `--target`，AI 无本机文件系统上下文 |
| 上传本机文件到云 | `dcs data push` | 源文件须在容器 `/work/{username}` 下，本连接器未暴露 terminal 工具 |
| 上传集群文件到云 | `dcs data upload` | 需集群文件路径，AI 无集群上下文 |
| 在线容器操作 | `dcs terminal *` | 未封装 |
| 文件方式投递 workflow | `dcs workflow run -j / --table` | 需本机文件路径，仅支持 `inputs` 数组方式 |
| 配置管理 | `dcs config *` | 未封装（由 MCP Server 自动处理） |
| 命令历史 | `dcs history *` | 未封装 |
| 片区管理 | `dcs region *` | 未封装 |

如用户需要这些能力，建议其直接使用 dcs CLI 或在 WorkBuddy 中安装支持这些能力的连接器。

## 禁止

- 不要尝试直接运行 `dcs` shell 命令（MCP 环境下无法 spawn 进程，且本连接器已封装所需能力）。
- 不要编造工具名或参数；不确定时调用 `list_projects` / `current_project` 等无副作用的工具确认上下文。
- 不要让用户把 PAT 粘贴到对话中，应通过 WorkBuddy 连接器表单配置。
- 不要尝试调用本连接器未暴露的 dcs 子命令（如 `terminal`、`data download`、`data upload`、`data push`、`config`、`region`、`history` 等）；如用户需要这些能力，告知其当前连接器暂未支持（详见上方「能力边界」）。

## 开发者参考

以下文档供连接器开发者查阅 dcs CLI 细节，**AI 在运行时不需要使用**（MCP 工具已封装相关能力）：

- [数据管理细节](references/dcs-data-manager.md)
- [在线容器 + 离线 analysis 细节](references/dcs-cloud-terminal.md)
- [Workflow 流程细节](references/dcs-wdl-manager.md)
