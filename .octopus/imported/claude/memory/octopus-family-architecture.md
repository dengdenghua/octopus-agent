---
name: octopus-family-architecture
description: Octopus 五仓家族结构 + octopus-storage(File Agent 文档 KB)+ 代码/文档 grounding 的域分工决策
metadata: 
  node_type: memory
  type: project
  originSessionId: 8aca05ae-c5bd-44e7-a9e0-c11f0ec07fb5
---

**五个同级仓**(`/Users/dangbei/Public/octopus/` 下):`octopus-agent`(中枢 agent 运行时 + work-mode UI)、`octopus-mobile`(远程/移动小脑,见 [[octopus-mobile-account-billing]])、`octopus-os`("NAS / appliance surface" 设备/盒子 OS 表面)、`octopus-enterprise`(企业面)、`octopus-storage`(本地安全数据小脑)。

**octopus-storage = File Agent / 数字资产管家 的真后端**(不是 octopus-os;两者都沾 NAS,os 是硬件表面、storage 是 AI 数据大脑):
- **独立可部署 Python 服务**(自带 `octopus_storage/` 包、app.py/cli.py/.venv/pyproject),本地 HTTP API,默认 `http://127.0.0.1:8767`。
- 端点:`GET /v1/manifest`(探活/能力)、`/v1/policy`(privacy/efficiency 模式)、`GET /v1/models`(**可插拔本地模型栈** embedding/reranker/OCR/vision/local-answer,**默认 `not_configured`**——要先配 bge-m3/nomic/Qwen 之类才能真跑)、`/v1/sources`(授权文件夹)、`/v1/index/jobs`、`POST /v1/search`(返回 `{hits:[{chunk_id,source_id,path,title,snippet,score,citation}], mode, message}`)、`/v1/answer`。
- **索引的是用户的文档/文件**(/Documents、PDF/图片 OCR),**不是代码**。原文件+向量留本地;privacy 本地答、efficiency 只送 Top-K 片段上云;答案带 source 引用。
- **家族铁律(它 README 明写)**:`octopus-agent` **不该自己持有用户的文件索引,必须通过窄 API 调 Storage,模型栈归 Storage 管**。

**关键澄清:octopus 里有两个"本地知识库",别混**:
- (a) **代码索引** `code_intelligence_skills` + `data/code_index.db`(进程内 SentenceTransformer all-MiniLM-L6-v2,纯 SQLite,**内嵌一体**,非服务、非外部向量库)——索引**仓库源码**,给编码 agent 做代码 grounding。**这不违反家族铁律**(README 说的是"用户文件索引"=文档,源码是 agent 自己的工作上下文)。
- (b) **octopus-storage**(同级服务)——索引**用户文档**,File Agent 正牌 KB。

**域分工决策(用户「按最优解」拍板,本会话实现)**:不是二选一,而是**两个域各用对的后端**——
- **代码 grounding → 留内嵌**(`code_index`):react 聊天的代码上下文。本会话 `e8b6005b` 已把 `search_persisted`(只读复用 `data/code_index.db` 的语义向量)RRF 融进 BM25;numpy/sentence-transformers 是**可选 extra**(本机没装→语义休眠→纯 BM25),`OCTOPUS_CODEBASE_SEMANTIC=0` 可关。**把代码 grounding 也走 Storage 是更差的**(文档/OCR 管线错配 + 把 agent 核心耦合到外部服务)。
- **用户文档 → 走 Storage API**(`f431ba5c`):新 `storage_skills.py` 的 `search_documents` 技能(零依赖 urllib 调 `/v1/search`,best-effort,Storage 没起/没配→`available:false`+可操作提示,不崩),注册进 `builtins.register_all` + 写进 `react_types` 目录(注册≠被用)。前端 File Agent UI 早已直连 Storage(`frontend/src/core/storage/api.ts`),这补的是 **agent 侧**(聊天里能查用户文档)。

**诚实边界**:Storage live 往返没真验过(服务没起、模型 not_configured);客户端 gating/解析/兜底/注册都确定性测了(mock urllib)。要真用:起 octopus-storage + 配 embedding 模型 + File Agent 面板里加授权目录建索引。

**统一本地驱动(补缺口,commits `7455c78d`+`58bf0e48`+`9ba50908`)**:用户问"能否一个本地 LLM 驱动全部"。结论:**生成/推理类能共用一个本地 chat 模型**(agent 大脑走 OpenAI-兼容客户端支持 Ollama/vLLM;Storage local-answer 也可插拔同端点);**嵌入/重排/OCR/视觉是另类专门模型**,不能用 chat LLM 当嵌入。**缺口=代码嵌入器写死**,已补:
- `runtime/memory/hemolymph/embedding_backend.py` —— 单一可配嵌入后端:`OCTOPUS_EMBED_URL`(OpenAI-兼容,如 Ollama `http://127.0.0.1:11434/v1`)+`OCTOPUS_EMBED_MODEL`(默认 all-MiniLM-L6-v2,远程如 bge-m3)+`OCTOPUS_EMBED_API_KEY`。URL 设了→远程 urllib(指 Ollama=真本地、零 Python ML 依赖;但通用 OpenAI-兼容,填云端点也照发,"remote"≠保证本地);否则进程内 **fastembed**(ONNX CPU 无 torch,最轻,commit `c4ba4813`)→ sentence-transformers → None。注:fastembed 之前只在嘴上说、代码没接,被用户点出后补的。**BUILD(`code_intelligence_skills._get_embedder` 现委托它)和 QUERY(`semantic_code_index`)共用同一后端**→语料/查询同模型(换模型要重建索引)。`semantic_code_index` 已改 numpy-free(array 读 float32 + 纯 py cosine),远程端点时本地零 ML 依赖。设三处(agent embed / 代码索引 / Storage)指同一 Ollama → 全栈一个本地嵌入模型 + 一个本地 chat 模型。
- **小白一键向导**:`local_brain.local_brain_status()` 出 5 项大白话清单(Ollama/对话模型/嵌入模型/Storage/代码索引,各带 ok+是什么+现状+下一步命令),探针可注入(全单测);`GET /api/local-brain/status`(`local_brain_router`,挂 app.py);前端 `local-brain-setup.tsx` 挂在 `/workspace/storage`(本地数据库)页顶,渲染后端中文串(无 i18n 漂移)。**已 live 端到端验证**(真后端路由 + Vite 渲染 + 截图,无报错)。
- **合并 vs 独立(用户问;决策=都不,走第三条,commits `b97d980b`+`52ec5c73`)**:不把 storage 代码合进 agent(它是全家共享服务 + 重 OCR/vision/torch 依赖 + 干净安全/扩展边界);也不停在"纯手动起两个服务"(小白痛点)。第三条=**独立包 + 可选托管协同启动**:`storage_supervisor.maybe_start_storage()` 在 `OCTOPUS_STORAGE_AUTOSTART=1`(默认关)时,`octopus serve` 把 storage 作为子进程拉起(已起则跳过;argv 解析 `OCTOPUS_STORAGE_CMD`→兄弟仓 `.venv/bin/octopus-storage`→PATH;shell-free;atexit 清理;后台线程探活不阻塞 boot;找不到/起不来都优雅降级)。契约仍是 HTTP,只改启动人体工学。向导 storage 步也提示了这个开关。
- **分发(用户问"独立包怎么下载/要不要云托管",决策 commits `b6c9be61`+`d6fd1f7f`)**:独立≠手动找下载,走 agent 已有的同一渠道。①**pip**:storage 是规范可装包(setuptools+console script),agent 加了 `[storage]` extra(`octopus-storage>=0.1.0`)→ `pip install "octopus-agent[storage]"` 从同一索引自动拉(源码期 `pip install -e ../octopus-storage`)。②**Docker**:新 `octopus-storage/Dockerfile`(python:3.12-slim,lean 无 torch 默认 extras `index,vector,embedding`,STORAGE_EXTRAS build-arg 可加重的)+ agent compose 加 `octopus-storage` service 挂 `profiles:["storage"]` → `docker compose --profile storage up` 起两个独立容器一条命令,默认 `up` 仍 agent 单进程;agent 端 `OCTOPUS_STORAGE_URL=http://octopus-storage:8767`。**"云托管"是任何包都要的事(agent 自己也要),split 只是同一渠道+1 artifact**。storage 仓当前无 .git,其 Dockerfile 在磁盘待该仓初始化后提交。docker build/up 本机没验(无 docker),compose YAML 已校验。
- 坑:本会话 ruff-format 漂移在 `code_intelligence_skills.py`/`app.py`/`builtins.py`/`cli.py` 反复被 `git add` 扫入;破法=`git checkout -- <file>` 还原 HEAD 再重贴我那几行(见 [[octopus-agent-generated-artifact-drift]])。

相关:[[octopus-agent-context-engineering]]、[[octopus-agent-multiagent-gap]]、[[octopus-mobile-account-billing]]
