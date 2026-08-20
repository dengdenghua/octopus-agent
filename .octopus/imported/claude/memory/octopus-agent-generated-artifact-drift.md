---
name: octopus-agent-generated-artifact-drift
description: 既有版本漂移雷区——naive 重生成 openapi-types 或全量 ruff format 会产生巨量无关 diff
metadata: 
  node_type: memory
  type: project
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

octopus-agent 有两处"naive 重做就爆炸"的既有漂移(自 `e1d4658` 基线导入即存在,非任何会话引入):

**OpenAPI 前端类型脱节**：`docs/openapi-snapshot.json` 与 `frontend/src/core/api/openapi-types.ts` 自基线起就不同步——快照有 ~23 条 `/api/agent-trace/*` 路径,types.ts 一条没有。用锁定版 `openapi-typescript@7.13.0`(锁文件=本地一致)从快照重生成 types 会产生 ~8000 行 diff(纯既有漂移)。**新增后端端点时**：`make openapi-snapshot`(改 Python 快照)必须做、diff 干净只含你的端点,`test_openapi_snapshot.py` 非写模式会拿 app OpenAPI 比对它(不更新会让该测试失败);但**别**跑 `make frontend-types` 提交——会把你的端点埋进 8k 行基线漂移。types 的 reconciliation 该单独成一 pass。**重要修正**:团队相关前端用的是 `frontend/src/core/teams/api.ts` 的**手写** TS 接口(`Team`/`TeamParticipant`/`UpdateTeamParticipantInput` 等),**不** import 生成的 openapi-types——所以团队治理的前端工作**不被这个脱债阻塞**,直接扩手写接口即可(本会话 commit 10dbaf8 已这么做)。脱债只影响真正 import openapi-types.ts 的地方。前端 i18n 加任何 label 需同改 5 文件:`core/i18n/locales/types.ts` + en-US/zh-CN/ja-JP/ko-KR(ja/ko 部分键是英文回退),`locale.test.ts` 会校验各 locale 形状一致。

**ruff format 版本漂移**：本地 ruff 0.15.12 与仓库当初格式化所用版本不同,`model_copy(update={...})` 等换行规则变了。`team_rooms_router.py` 在 HEAD 原版就有 16 处 `ruff format` 不一致 hunk。**只**让新增代码匹配周围风格(`ruff check` 能过即可);**别**全量 `ruff format` 重排。判断有没有引入新违规：比对 HEAD vs 工作副本的 `ruff format --diff <file> | grep -c '^@@'` hunk 数,数目不增即 OK。

**并发会话**：本仓库常有多个 `claude --output-format` 会话同时往 main 提交(本会话期间另一会话在提交 injection-taint 工作,HEAD 在我准备提交时前移了两次)。提交务必用显式 pathspec `git -c core.safecrlf=false commit -F msg -- <files>`(临时索引,不碰别人暂存区)隔离自己的文件;git 靠 index.lock 串行化,线性历史无冲突。**并发会话会改/提交你正在重构的同一文件**(不只"别的文件"):拆 `team_rooms_router.py` 这次,任务说它 1271 行,但另一会话已把 delegation 功能 commit 进去变 1398——任务里的行号/函数清单可能已陈旧。处理:先 `stat -f %m` 盯住目标文件+其测试直到静默(本次约 10 分钟无写后该会话已 commit `de8bcbd` 转去做 realtime_*),再**重读全文**对最新状态动手,别信任务给的行号。后台 watcher 盯 mtime 要用**绝对路径**(`cd` 在后台 compound 命令里不生效,相对路径全 miss 会假"settled")。

**god_files_baseline.txt 是共享文件,常有并发会话的大段未提交重生成**(本次工作副本含 siphon→gateway 改名+一堆新 god 的整表重写,未 commit,`--write-baseline` 跑出来的)。你拆瘦一个 god 后 `god_file_check --strict` 会报 `SHRUNK`(这其实=成功信号,证明 <1000),要 exit 0 得删掉该文件那一行;但**别 commit 这个 baseline**——只在工作副本删你那一行(留并发重生成给对方提交),自己的 commit 只含代码文件。文件真 <1000 后任何 `--write-baseline` 都不会再收录它,自愈。另:拆 god file 时纯函数抽取往往不够(本次抽完 speaker-policy 仍 ~1149),真正掉到 <1000 得把大的**有状态** handler(如 WS handler 354 行)也搬出去(传 context dataclass,body 把 ctx 解包成原局部名即可近乎逐行平移)。

**2026-06-23 再次坐实并发提交 + hunk 级隔离法**：会话期间 HEAD 从 `3c3b5499` 前移 3 个提交(ECHO reskin / codex partner / 本地伙伴 label),并发 agent 用类似 `git add -A` 把我**未提交**的 `local_partner_bridge.py` 改动 + 新注册的 `agents/local_claude_code/` **原样卷进了它的提交**(`git show HEAD:file` 出现我一字不差的 edit,但 `git status` 显示干净)。教训:动手提交前先 `git log --oneline` 对比会话起点 HEAD,被卷走≠丢失。当我自己的改动跟一堆 WIP 纠缠在同一文件(locale 各 7~11 hunk,只 1 个是我的)时,**外科暂存**:`git diff HEAD -- f` 按 `@@` 切 hunk,只保留含我标记的 hunk + 文件头,`git apply --cached --recount` 暂存(--recount 让 git 修行号,免去手算)。100% 我的文件(sidebar-footer.tsx)直接 `git add`。提交后 `git diff --cached` 核验只含我的行,工作区那 1245 个变更原封不动。

相关：[[octopus-agent-dev-environment]] 预存失败基线、[[octopus-agent-audit-verification-lesson]] 先核查再动手、[[octopus-local-cli-partners]] 本地伙伴运维。
