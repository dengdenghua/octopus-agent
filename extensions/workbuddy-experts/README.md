# WorkBuddy Experts — 领域专家 / 专家团(Fork)

> 从本地 `WorkBuddy.app 5.3.14`(腾讯)解包 fork 的**领域专家与专家团**完整资产,
> 保留原插件市场结构,可直接作为 marketplace 加载或作为参考改造源。
>
> 源: `/Applications/WorkBuddy.app/Contents/Resources/app.asar` + `~/.workbuddy/plugins/marketplaces/experts`
> 解包日期: 2026-08-19

## 目录结构

```
workbuddy-experts/
├── README.md                        # 本文件
├── experts-index.json               # 统一索引(14 个:3 专家 + 2 专家团 + 9 写作专家)
├── curated-experts.json             # 官方内置推荐清单(60 个候选:50 专家 + 10 专家团)
├── marketplace-experts/             # 完整专家市场(fork,含 .codebuddy-plugin/marketplace.json)
│   └── plugins/
│       ├── senior-developer/        # 专家(agent) 高级开发工程师·吴八哥
│       ├── workspace-builder/       # 专家(agent) 数字工作台构建
│       ├── embedded-firmware-engineer/ # 专家(agent) 嵌入式固件
│       ├── seo-content-team/        # 专家团(team) 7 角色 SEO 内容营销
│       └── stock-partner-team/      # 专家团(team) 6+1 投研圆桌(腾讯自选股)
├── builtin/
│   └── tencent-docx-experts/        # 内置 9 个写作专家(SKILL.md 格式)
├── specs/
│   └── expert-manager/              # 官方专家包规范 v2.0 + 生成/校验工具链
│       ├── SKILL.md                 # expert-manager 技能说明
│       ├── references/              # plugin-json-spec / agent-md-spec / team-spec / avatar-spec
│       └── scripts/                 # init/validate/register/package/batch_create .py
└── templates/                       # 专家系统系统提示词模板(.tpl)
```

## 两种专家格式

| 类型 | `expertType` | 说明 | 示例 |
|---|---|---|---|
| 专家 | `"agent"` | 单角色,`agents/*.md` 一个文件 | senior-developer |
| 专家团 | `"team"` | 多角色,主理人 + N 成员,`teamInfo` + `members[]` | stock-partner-team |

每个包结构:
```
<expert>/
├── .codebuddy-plugin/plugin.json   # 清单(expertType/agentName/members/tags...)
├── agents/*.md                     # Agent 定义(YAML frontmatter + Markdown 正文)
├── skills/                         # 可选:捆绑技能
├── avatars/                        # 头像
├── bin/                            # 可选:团队初始化脚本
└── references/ assets/ license/    # 可选
```

## 专家团协作机制(铁律)

- 主理人(lead)负责 `TeamCreate → Agent spawn → SendMessage` 编排
- 成员独立产出,所有信息流经主理人中转,成员不直连
- 5 条红线:禁代写、禁跳阶段、禁成员直连、禁 spawn 主理人、禁跳过 TeamCreate
- 12 大行业分类:01-ProductDesign … 12-IndustryConsultant

## 使用方法

- **作为市场加载**: 把 `marketplace-experts/` 指给 WorkBuddy 的专家市场扫描目录
  (原路径 `~/.workbuddy/plugins/marketplaces/experts/`,可直接替换)
- **格式参考**: `specs/expert-manager/references/` 是最权威的格式规范
- **生成新专家**: 用 `specs/expert-manager/scripts/init_expert.py` + `validate_expert.py`
- **移植到 octopus-agent**: 本仓库 agent 格式为 `profile.jsonc + agent-core/`,
  与 WorkBuddy 插件格式不同,需按 `agents/<id>/` 规范转换(见 octopus `agents/` 目录)

## 版本 / 出处

- 产品: WorkBuddy Desktop 5.3.14 `com.workbuddy.workbuddy` (Tencent)
- 专家市场源: `~/.workbuddy/plugins/marketplaces/experts`
- 内置专家源: `app.asar/resources/plugins/workbuddy-builtin/builtin-plugins/tencent-docx/experts`
- 推荐清单源: `app.asar/resources/builtin-expert-recommendations/curated-experts.json`

---

## ✅ octopus-agent 原生兼容(2026-08-19)

`runtime/execution/misc/agent_packs.py` 已支持 `.codebuddy-plugin` 格式:
`scan_agent_pack()` 可直接预览本市场(5 插件 / 17 agents / 10 skills),
`import_agent_from_pack()` 可把任意专家导入为 `agents/<id>/` 标准 agent。

**使用方式(网关 API):**
- 预览: `GET /api/agent-market/packs/preview?path=extensions/workbuddy-experts/marketplace-experts`
- 导入: `POST /api/agent-market/packs/import-agent`
  `{"path": ".../marketplace-experts", "agent_name": "embedded-firmware-engineer", "agents_root": ".../agents", "skills_root": ".../skills"}`

**说明:**
- agents/*.md(带 YAML frontmatter)与 skills/**/SKILL.md 格式与 Claude/Codex 包完全一致,可直接复用
- WorkBuddy 特有字段(expertType/teamInfo/members/displayName/profession)作为额外元数据保留在 frontmatter
- 团队主理人依赖的 TeamCreate/Agent spawn/SendMessage 是 WorkBuddy 运行时能力;octopus 用自己
  的 subagent 编排(ephemeral_agents),团队协作流程需按 octopus 机制适配,格式本身无需转换

---

## 🧩 octopus-agent hub 集成(2026-08-19)

### 1) Skill 市场 — ✅ 已替换
`scripts/install-to-hub.py` 把 WorkBuddy 内容灌进本地 skill hub:
- **19 个 skill** → `~/.octopus/skills/`(10 个市场技能 + 9 个内置写作专家,各带 SKILL.md + meta.json)
- **registry.json** 重建 → `python -m runtime skills list|search|info` 及 UI skill 市场可见
- 卸载: `python3 scripts/install-to-hub.py --remove`

### 2) Agent 商店(专家/专家团)— ✅ 已替换
`scripts/port-to-octopus-agents.py` 把 5 个 WorkBuddy 专家包转成原生 octopus agent:
```
agents/embedded_firmware_engineer  固件通      [engineering]
agents/workspace_builder           小台        [engineering]
agents/senior_developer            吴八哥      [engineering]  +4 skills
agents/seo_content_team_lead       SEO内容营销团队 [marketing] +3 skills  [team]
agents/stock_partner_lead          腾讯自选股投研团 [finance]  +3 skills  [team]
```
- 从 plugin.json 提取 displayName/profession/categoryId/tags/avatar,生成 profile.jsonc + agent-core
- 自动映射 12 类 WorkBuddy 分类 → octopus category,拷贝头像与捆绑 skill
- 卸载: 删除对应 `agents/<slug>/` 目录即可

### 3) 市场源(agent packs)— ✅ 已兼容
`runtime/execution/misc/agent_packs.py` 支持 `.codebuddy-plugin`:
- 预览: `GET /api/agent-market/packs/preview?path=.../marketplace-experts`
- 导入: `POST /api/agent-market/packs/import-agent`

### 4) 未覆盖 / 需适配
- **团队编排**: 专家团主理人依赖 WorkBuddy 的 TeamCreate / Agent spawn / SendMessage
  运行时能力。octopus 用自己的 subagent 机制(ephemeral_agents),团队协作流程
  需按 octopus 方式适配,主理人 agent 本身已可用。
- **westock 连接器**: stock-partner-team 依赖腾讯自选股 westock-mcp,OAuth 连接器
  需单独配置后才会有真实行情数据。

---

## 🌐 远程全量目录(2026-08-19 同步)

**WorkBuddy 专家中心实际有 421 个专家**(369 agent + 52 专家团),不是 5 个 ——
本机 `marketplace-experts/` 那 5 个只是**当时实际下载安装过的**包。

`remote/` 已同步全量轻量目录:
```
remote/
├── expert_center.json        # 权威清单:421 专家 / 15 大类(JSON 元数据全量)
├── INDEX.md                  # 421 个的可读索引
└── agents/<plugin>/*.md      # 243 个可下载的 lead agent 定义
    # 其余 177 个 manifest 里的 promptFile 是过期路径(HTTP 404,应用同样跳过)
```

**全量 bundle(421 个完整包,~1.3G)**已下载到 `remote/bundles/`(本机可用),
但因体积原因**不进 git**(见 `remote/bundles/.gitignore`)。重新拉取:
```bash
python3 scripts/pull-remote-catalog.py --bundles --strip-avatars   # 剥头像
python3 scripts/pull-remote-catalog.py --bundles                   # 保留头像(1G+)
```

bundle 内含团队全部成员 agents/*.md、skills、references、bin、settings.json;
部分专家携带重型数据资产(RAG 语料 `.npz` 386MB、DuckDB 数据库、PDF 资料、anydev 二进制等)。

---

## ☁️ 云端商城(2026-08-19 已上线)

**做成了我们自己的商城,已发布到 GitHub Pages:**
👉 https://dengdenghua.github.io/workbuddy-expert-market/

纯静态商城(无构建工具),数据来自 `storefront/data/expert-store.json`(421 专家 / 15 类):

```
storefront/
├── index.html            # 商城页:左侧分类 + 卡片网格 + 详情弹窗
├── app.js                # 纯原生 JS:搜索/分类/排序/详情/复制提示/下载
├── style.css             # 响应式样式(桌面 + 移动)
└── data/
    ├── expert-store.json     # 421 专家(含 bundleUrl/头像/分类/quickPrompts/meta)
    ├── expert-store.cos.json # 发布前 COS 版数据备份(本地保留,不进站点)
    └── skill-registry.json   # 19 个技能的云端注册表(供 SkillMarket 拉取)
```

**发布命令:**
```bash
# 只发商城页面(默认,数据里 bundleUrl 保持腾讯 COS 直链)
python3 scripts/publish-cloud.py --repo dengdenghua/workbuddy-expert-market

# 发商城 + 把本地 remote/bundles(1.3G)传成 GitHub Release 资产,彻底自托管
python3 scripts/publish-cloud.py --repo dengdenghua/workbuddy-expert-market --upload-bundles
```

**发布内容:** `storefront/` 整体推到目标仓库 `gh-pages` 分支 + 自动开启 GitHub Pages。

---

## 🔌 octopus-agent 云端市场接入(2026-08-19)

### Agent 市场(专家/专家团)— ✅ 新增云端源
`runtime/platform/plugins/cloud_expert_store.py` + `agent_world_router` 新增接口:

| 接口 | 说明 |
|---|---|
| `GET /api/agent-market/cloud/store` | 云端专家列表(421,支持 category/search/sort/分页,与本地 /store 同构) |
| `GET /api/agent-market/cloud/store/categories` | 15 大分类 + meta |
| `GET /api/agent-market/cloud/store/{id}` | 专家详情(bundleUrl/quickPrompts/描述) |
| `POST /api/agent-market/cloud/store/{id}/install` | **一键安装**:下载 bundle→安全解压→`import_agent_from_pack` 导入为原生 agent |

- 数据源默认远程 `raw.githubusercontent.com/dengdenghua/workbuddy-expert-market/gh-pages/data/expert-store.json`
  (环境变量 `OCTOPUS_CLOUD_EXPERT_URL` 可覆盖),网络不可用时自动回退到本地
  `extensions/workbuddy-experts/storefront/data/expert-store.json`
- 安装复用已有 `.codebuddy-plugin` 兼容(`agent_packs.py`),专家 → `agents/<slug>/`,捆绑 skill → `skills/public`
- 已测试:本地镜像 421 条、搜索/分类、真实从 COS 下载并安装 `content-creator` → `content_creator` agent + 5 skills

### Skill 市场 — ✅ 支持云端注册表
`runtime/platform/plugins/skill_market.py`:
- `_fetch_registry()` 现在会拉取云端 `skill-registry.json` 与本地 registry 合并(本地同名优先)
- 远程 URL 默认 `raw.githubusercontent.com/.../gh-pages/data/skill-registry.json`,环境变量 `OCTOPUS_SKILL_REGISTRY_URL` 覆盖
- 拉取失败静默回退本地,不影响原有行为

### 测试
```
tests/test_cloud_expert_store.py   # 9 例:本地镜像/搜索/分类/团队标记/解压安全/包根定位
```

---

## 🔌 插件 / 连接器商城(2026-08-19)

商城新增**插件/连接器**页(纯静态):
👉 https://dengdenghua.github.io/workbuddy-expert-market/plugins.html
(或同域名 `/plugins.html`,数据 `storefront/data/plugin-store.json`)

**123 项 = 我们的 Codex 插件 15 个 + WorkBuddy 连接器 108 个:**

| 来源 | 数量 | 说明 |
|---|---|---|
| Codex 插件 | 15 | `~/.codex/plugins/cache` 里的 google-drive / figma / sites / browser / chrome / visualize … |
| WB 连接器 | 108 | mcp 84 / cli 22 / skill-only 2,含 auth_mode + 捆绑技能数 |

生成:
```bash
python3 extensions/workbuddy-experts/scripts/build-plugin-store.py
```

配套的 **octopus 认证编排层**(`runtime/platform/connectors/`)让连接器"连得上":
`POST /api/connectors/{id}/connect`(token/CLI 登录)→ `GET /api/connectors/{id}/headers`
(auth 头注入)→ `GET /api/connectors/{id}/status`。详见
`extensions/workbuddy-connectors/README.md`。
