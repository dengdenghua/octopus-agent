# 章鱼器官 · 生物学类比说明

> 这里**不是代码** · 只是每个"章鱼器官"命名的概念文档。
>
> 真实 Python 实现都在 [`runtime/`](../../runtime/) 下的同名子包。
> 比如 `eyes` 的代码在 `runtime/eyes/` · 这里的 `eyes/` 只是一段说明。

## 20 个器官索引

### 慢路径（Deliberative）
- [`cerebrum/`](cerebrum/) — 中枢脑 · 规划 / 分解 / 反思
- [`ganglia/`](ganglia/) — 神经节 · 分布式腕足控制

### 快路径（Reactive）
- [`spinal_cord/`](spinal_cord/) — 脊髓 · 反射动作 · 不经大脑
- [`nerves/`](nerves/) — 神经 · 消息总线 / 工作流图

### 执行单元
- [`arms/`](arms/) — 腕足 · 半自主 worker agent (×8)
- [`tentacle/`](tentacle/) — 触腕 · 移动 / 跨设备执行触点
- [`suckers/`](suckers/) — 吸盘 · 技能库
- [`beak/`](beak/) — 喙 · 工具执行引擎

### 感知
- [`eyes/`](eyes/) — 眼 · 模型适配 / 视觉输入
- [`skin/`](skin/) — 皮肤 · 环境感知

### 运输与边界
- [`siphon/`](siphon/) — 漏斗 · 流式 I/O
- [`mantle/`](mantle/) — 外套膜 · 沙箱 (local/docker/ssh/k8s)
- [`hemolymph/`](hemolymph/) — 血淋巴 · 上下文流 + Blackboard

### 记忆与进化
- [`genome/`](genome/) — 基因组 · 长时记忆 / 检查点
- [`regeneration/`](regeneration/) — 再生 · 反思 / 技能锻造
- [`camouflage/`](camouflage/) — 拟态 · 策略 A/B

### 自我保护
- [`immunity/`](immunity/) — 免疫 · 身份 / 适应性风控
- [`ink/`](ink/) — 墨囊 · 熔断 / 预算上限
- [`hearts/`](hearts/) — 心脏 · HA 调度 (×3)

### 广播
- [`chromatophores/`](chromatophores/) — 色素细胞 · 腕间状态广播

## 为什么分成两套

把"隐喻 / 设计思路"和"可运行代码"物理分离 · 避免初次看仓库的人被
20 个只有 README 的空文件夹迷惑 · 以为那些是模块入口。

想读真代码 → `runtime/` · 想理解"为啥叫这名" → 这里。
