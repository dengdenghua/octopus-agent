---
name: octopus-storage-and-echo-hardening
description: 生态扩到6项目(+echo-universe-engine IP层/+octopus-storage 数据层);storage(5commit)+echo(4commit)数据完整性/安全修复均完成,两库已push到GitHub私有(dengdenghua/octopus-storage + echo-universe-engine)
metadata: 
  node_type: memory
  type: project
  originSessionId: be9c00f3-d3d2-41c6-b43b-a93a9b957a39
---

**2026-06-24 发现生态从4扩到6个项目**（顶层 README 已列5个 + echo 独立）：
- **echo-universe-engine**（IP/内容层，~995行 Python/FastAPI，**独立 git 仓库，全树有大量未提交 WIP**）：canon-first 虚构宇宙治理工厂——9角色/11派系/世界圣经/经济(钱包/订阅/商品)/身份权限梯队/canon评审治理/NPC路由。已把9个 ECHO 角色作为 SOUL.md 导入 octopus-agent 的 agent 人格（echo_zero/kane/eve/luna/raven/shion/noah/leon/mira_voss + general=Eve/coder=Kane/admin=Leon/desktop_operator=Raven/ecommerce_mind=Shion 等复用槽）。定位：ECHO 是 IP 母体，octopus 是运行时神经系统。最大缺口仍是"互动体验层缺失"（生成/治理工具齐全，但用户无法"进入"宇宙互动）。
- **octopus-storage**（数据小脑层，~966行 Python/FastAPI）：octopus-agent 工作台「File Agent/数字资产管家」背后的本地安全数据服务——授权目录→OCR→分块→embedding/向量→检索→隐私门控 RAG 问答。privacy模式本地检索本地答；efficiency模式只发Top-K片段到云。

**octopus-storage 本次加固（2026-06-24 我做，5 commit 含 baseline，已 push 到 GitHub 私有库 dengdenghua/octopus-storage）**：storage **此前根本不是 git 仓库**（生态唯一漏的，但 .gitignore 已备好），我 `git init` 建基线(3c2292b)。基线 30 测试绿 + ruff(严格规则 E/F/W/I/UP/B/SIM/RET)绿，**但绿色掩盖真 bug：测试环境无 sqlite-vec、无 vision/embedding 后端 → 所有向量/视觉路径的 bug 测不到**。修复：
- **indexer 数据完整性+死代码(135b27a)**：① `VISION_EXTENSIONS ⊆ OCR_IMAGE_EXTENSIONS` 且 OCR 分支(if)优先于视觉分支(elif)→视觉分支**永不可达**，README/manifest 宣称的 search.vision(文字搜图)是**死代码**；改合并判断激活。② upsert_chunks/upsert_vectors 是"先删该source全量再插"语义，但 vision 循环每图各调一次→清空文本chunk/向量；改为累积后各调一次 + vision chunk_id 用列表索引(防同名图片主键冲突)。
- **安全收口(ff9d36e)**：删 CORS `allow_origin_regex=r"^file://.*$"`(任意本地HTML页可跨域打全API)；token 改 `os.open(O_CREAT|O_WRONLY|O_EXCL,0o600)` 原子创建(消除 write→chmod 间 world-readable 窗口 + 不再静默吞 chmod 失败)；401 不再回显 token 文件路径。
- **健壮性/正确性(ff9d36e)**：search_chunks 对 FTS5 特殊字符(`"`/`*`/`NEAR`)不再抛500(原始查询→失败退回字面短语→再失败空)；update_index_job 进 running 写 started_at(原永远null)；watcher.stop() join 防抖线程(原只 join observer)；create_source 捕 `sqlite3.IntegrityError` 类型而非匹配"unique"字符串；allow_snippet_export 真正生效(原是 dead flag，云端答现尊重它)。
- **API竞态(62c2987)**：`POST /v1/index/jobs` 原 `return db.get_index_job()` 重查库→后台daemon线程可能已改 running→202返回status不确定；紧循环复现 **12/30 flaky**，改 `return job`(pending)后 **0/30**。
新增 `tests/test_regressions.py`(3测试;并用 git 回退 indexer 验证测试有区分能力)。终态 33 passed + ruff 绿。

**echo-universe-engine 数据完整性已修（2026-06-24 我做，工作树未 commit）**：① 新增 `store.atomic_write_text`(临时文件+os.replace)，economy/bindings/identities 的 `_save_*` 全改原子写(防写中途崩溃损坏 json)；② economy 加模块级 `_STATE_LOCK` 串行化 record_wallet/grant/activate/**purchase_product** 的 check-then-act(防钱包并发双花/丢交易)；③ bindings `_load_bindings` 加 try/except→`BindingError`(损坏不再裸500连锁；identities._load 本就有防御没动)。90测试绿+ruff绿+inline验证(原子写无.tmp残留、损坏抛BindingError)。**整批 WIP 已收尾提交（用户确认"收尾"后）**：把 ECHO 宇宙可玩层(经济/身份/治理/NPC/realm/skin/绑定 + octopus 集成 + console + 10测试 + data配置 + 内容,~2816改行+23新.py)组织成 4 个 commit 提交到 main：**7ca2987** feat核心(echo_engine+data*.yaml+tests+integrations,含我的数据完整性加固) / **9223d31** feat(console) / **39088ad** content(009_mira_voss+assets+outputs生成产物) / **853718a** docs(README+architecture_codex)。提交前核验:ruff全量绿、0 TODO/半成品、90测试绿。data/outputs/assets 入 git 是用户设计(README 的 ECHO_AUTO_GIT_COMMIT)。**已 push**:用户选私有,`gh repo create dengdenghua/echo-universe-engine --private` 新建 GitHub 私有库并推送 main(2026-06-24)。至此 echo 加入其他 4 个 octopus 项目的 GitHub 托管行列(账号 dengdenghua,私有)。**非bug未动(设计层/需产品决策)**：echo 整个 HTTP API 无认证(user_id/reviewer 客户端自报)=MVP现状→canon 评审门禁(journal.py:160 仅 realm_event 校验 reviewer，candidate_output 无校验即可标 accepted→promote)可绕过=产品决策(test_smoke 锁定 missing event_id 返200)；bindings 多人绑同角色需先定独占语义；digital_life.py 有WIP，没碰它的非原子写。

相关：[[octopus-ecosystem-and-os-fork]]、[[octopus-agent-ci-baseline-state]]、[[octopus-optimization-scan]]。
