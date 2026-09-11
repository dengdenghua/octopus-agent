# HUB 多来源技能目录

2026-09-11 已接入并部署到本地 8310 / 4173。

- Echo 目录继续使用既有目录接口，独立于外部来源加载。
- OpenAI、Anthropic、Vercel 从官方 GitHub 仓库读取 SKILL.md，缓存一小时；读取失败时展示缓存或来源不可用状态。
- Skills.sh 使用其开源 CLI 同款 `/api/search` 接口，输入至少两个字符后检索，最多取 30 条，缓存五分钟。这个数字不是市场总量。
- HUB 增加来源筛选，显示 Echo、外部已载入、本地及合并数量。来自同一仓库且名称相同的官方条目和搜索结果去重；不同仓库同名技能独立展示。
- 技能详情保留原仓库链接、版本及上游提供的许可、兼容信息。

## 安装边界

用户点击安装后，通过现有登录、管理员和部署模式检查。共享/商业部署仍禁止热安装未经发布审核的技能。

安装从服务端已发现的条目解析 GitHub 仓库，固定提交 SHA，使用既有公共 HTTPS 校验下载；限制下载、展开体积和文件数，拒绝目录穿越。链接文件不写入磁盘，若所选技能依赖链接文件则明确拒绝安装。只复制所选目录及仓库许可，保留附带脚本和参考文件，不执行脚本、不自动安装依赖、不授予工具权限。

运行时技能名使用仓库及原名称的命名空间，避免覆盖已安装技能。来源和固定提交写入 `.source.json`。已有同标识技能保持不变；自动更新、卸载及用户自定义仓库入口不在本轮范围。

Skills.sh 返回仓库与技能名；安装时解析该仓库当前提交。未找到唯一匹配项时给出错误，不猜测其他路径。GitHub API 使用匿名公共访问，可能受限流影响。外部指令与当前引擎的工具兼容性仍取决于具体技能，安装成功不等于其所有操作均可执行。

## 实测

- 官方目录：OpenAI 39、Anthropic 20、Vercel 9，共 68 条。
- 初始页面：Echo 178 ＋外部 68 ＋本地独有 12 ＝258；本地已安装 47。
- Skills.sh `frontend` 查询返回 29 条，和官方目录有 1 条重合，外部合并结果 96 条。
- 三个官方来源分别在临时目录完成真实下载、固定版本、资源解包验证，没有批量安装到用户技能目录。
- 后端 37 项通过，前端 9 项通过，生产构建通过。既有的 POSIX 文件权限测试在 Windows 上不适用，本轮未修改该测试；全仓 TypeScript 检查仍存在其他文件的既有错误，本轮修改文件未报告类型错误。
- 验证日志：`.codex-run/external-skills-tests.log`、`external-skills-frontend.log`、`external-skills-live.log`、`external-install-smoke.json`。

参考协议：[Vercel Skills CLI](https://github.com/vercel-labs/skills)、[OpenAI Skills](https://github.com/openai/skills)、[Anthropic Skills](https://github.com/anthropics/skills)。


## MiniMax Design public featured catalog (2026-09-11)

Added `minimax-design` discovery through the public landing-page endpoint
`https://design.minimaxi.com/api/v1/skills/market?page=1&page_size=20&source=official-featured`.
Live verification read 35 entries over two pages; this is the featured subset, not the whole market.
The adapter preserves Chinese names, summaries, tags and source versions, caches complete snapshots for one hour, and keeps the previous complete snapshot if pagination or networking fails.

Versioned entries now support local installation through the public endpoint
`https://design.minimaxi.com/api/v1/skills/market/download?name=<original-name>&version=<catalog-version>`.
No MiniMax login or API key was needed for package download. Entries missing a valid version remain browse-only. Cache schema 2 refreshes the previous browse-only catalog.

The installer validates the package name and `meta.yaml` version, limits ZIP download and expanded sizes, rejects links, special files, path traversal and Windows filename collisions, and atomically installs the complete resources. It retains `SKILL.original.md` and records the source/version and observed archive SHA-256 in `.source.json`; this is a provenance checksum, not verification against the market's undocumented hash. Runtime names are namespaced to prevent overwrites; existing installations and edits are preserved. Installation never executes downloaded scripts.

All 35 featured packages passed live download and installation into temporary directories; report: `.codex-run/design-package-audit.json`. These are portable instructions/resources, not bundled image/video/audio services. Users still need compatible tools, models and any required provider credentials for media generation. Original source and compatibility information remain visible in the UI. Same original names participate in multi-source grouping; translated titles and merely similar workflows are not merged.

Validation after package installation support: 31 backend tests and 14 Skills panel tests pass; production build passes. Full TypeScript checking still has unrelated baseline errors; no diagnostics in the changed frontend files. Logs: `.codex-run/design-install-tests.log`, `design-install-ui-tests.log`, `design-install-build.log`, `design-install-types.log`.
