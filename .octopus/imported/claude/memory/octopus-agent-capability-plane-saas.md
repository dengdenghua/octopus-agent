---
name: octopus-agent-capability-plane-saas
description: 把角色模板/数字分身/技能/插件/技能包抽成共享多租户 SaaS(Cortex Registry)的设计方案
metadata:
  node_type: memory
  type: project
  originSessionId: 73dba696-f7dc-4ee6-899f-63f46a601f05
---

用户目标:把 octopus 的**角色模板/数字分身/技能/插件/技能包**做成独立多租户 SaaS+API,让几个**同级产品复用而不用各自 fork**。26-agent workflow(map→3方案对抗评分→综合)产出方案,每条带 file:line 实证。

**最诚实的核心结论**:fork **不能全灭**。技能 `handler` 是必填 Python Callable(registry.py:39),绑死 playwright/pyautogui + 各产品执行 gate 栈;serve 它就得 import 391 模块 runtime(`runtime/__init__.py:23-50` 是 eager-import 墙)。**执行代码天然各产品自持**。真正在重复 fork 的是**数据**(`agents/<id>/` 目录被复制)→ 能做的是把数据 fork 变成共享版本化 registry,执行代码靠 manifest 广告+校验。评委三套方案在"能否终结 fork"维度都只给 3/5,一致确认执行 fork 不可消除。

**现状成熟度(实证)**:角色模板/数字分身/技能=production;插件/技能包/API-租户=partial;存储底座=production 但抽取难度**高**(全本地磁盘 JSONL/MD,**无 tenant 列**)。**已有可直接抽**:`agent_packs.py`(runtime-free 纯数据扫描器,17 agent 这么导入)、`identity.py`/`web_auth.py`(零 runtime 依赖、抗 alg-confusion HS256,逐字搬)、插件/技能市场 API 契约+前端已存在(`skill_market_router`/`plugin_hub_router`/`agent_world_router`),只是后端 vaporware(`DEFAULT_REGISTRY_URL` 404、`publish()` 只打印提 PR)。**死代码勿盖楼**:`arms/skill_manifest.py`(零消费者)、StateStore File/SQLite 后端、`did` 字段(只写不读)、social/ratings stub。

**推荐架构(评分 20 vs 19/19 胜)= 三 deployable**:① **Cortex Registry SaaS**(Postgres+对象存储+无状态 FastAPI,**永不 import runtime**)= 唯一事实源,持有五类不可变版本化定义 + 多租户/RBAC/签名/版本DAG解析器/市场;② **octopus-runtime SDK**(pip,各产品 vendor)= 拉 lockfile→验签→落到**现有磁盘布局** `agents/<id>/` + `~/.octopus/skills/`→绑到产品自己的 runtime;③ 产品保留 100% 执行(GraphRuntime/gate 栈/_ARM_FACTORIES/原生 suckers)。**硬规则:定义过线,执行权永不离开产品。**

**基石重构(prereq,P0)**:拆 `loader.load_agent` → `parse_template(dir)→TemplateSpec`(纯)+ `instantiate(spec,runtime)→Agent`;顺手修 **model-drop bug**(loader.py:505 Agent ctor 从不传 model=)+ 删重复 `_memory_tier_paths`。SaaS 和 SDK 都只用 parse 半。

**技能=callable 解法**:kind=`prompt_pack`(主力/默认/零代码过线,handler 客户端 `_make_prompt_handler` 再生,真活由产品已有原子技能干)/`code_backed`(v2,签名 tarball+importlib,**exec_module 在 gate 前跑=import RCE→必须子进程沙箱**,v1 禁)/`native_builtin`(重型 suckers 只存元数据,实现 ship 在产品)。

**5 个关键决策(需用户拍板)**:① 多语言 vs 纯 Python(建议 REST+OpenAPI 当契约但先只发 Python SDK)② 只 registry vs 托管执行(建议**只 registry,不可妥协**)③ code_backed 分发(建议 v1 禁/v2 签名沙箱)④ 分身可变状态(建议 v1 产品本地+export bundle)⑤ 默认 deny + loader 拆分先落 octopus-agent。

**路线**:P0 拆 loader(repo 内 1-2 周)→ P1 MVP(octopus-agent 自当首个消费者,从最小 SaaS 拉一个 prompt_pack 技能跑通全链路,启动后杀 SaaS 零影响=证明不在热路径)→ P2 多租户+签名+版本DAG+RoleTemplate → P3 插件/包/分身+真市场(接已有前端)→ P4 code_backed 沙箱+多语言客户端。**风险**:集中化(一个 SaaS 握全部 registry+密钥+签名钥=爆炸半径比各自 fork 更大,需非对称签名+轮换)、冷缓存+registry 宕机首启是唯一硬失败、消费侧租户隔离 SaaS 强制不了(全局单例 SkillRegistry)。

完整结果:`tasks/wpfgxxvoq.output`(233KB,workflow wf_371c0363-216)。相关:[[octopus-agent-multiagent-gap]]、[[octopus-agent-integration-debt-audit]]、[[octopus-agent-automation-stacks]]、[[octopus-agent-audit-verification-lesson]]
