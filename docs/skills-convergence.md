# 技能双轨收敛（audit A-05）

## 现状（2026-08 复核）

技能目录当前存在两个物理位置：

| 位置 | 角色 |
|---|---|
| `skills/public/<name>/SKILL.md` | **规范源**（加载器优先，`agentskills.default_skills_dir`） |
| `runtime/execution/all_skills/<name>/SKILL.md` | **wheel 回退**（裸安装无外部资源根时使用） |

加载顺序：外部 `skills/public/` 存在即用；否则回退 `all_skills/`。

## 重叠清单（`tools/lint/skill_cross_dir_check.py` 基线 = 4）

`code-quality`、`frontend-design`、`pdf`、`typescript-best-practices`
在两个位置都存在且 SKILL.md 已分叉（public 侧更新）。检查器把数量
冻结在基线 4——**只增会挂 CI**，每迁移一个必须手动降基线锁定。

## 收敛路径

1. 对每个重叠技能：以 `skills/public/` 为准，删除
   `runtime/execution/all_skills/<name>/` 副本。
2. `python tools/lint/skill_cross_dir_check.py --update-baseline`
   降基线（4 → 3 → … → 0），把胜利锁进 ratchet。
3. 目标终态：**单一技能树** —— `skills/public/` 是唯一事实源；
   `all_skills/` 保留为「由 public 生成的 wheel 回退镜像」，两处内容
   由同一脚本同步，不再允许手工分叉。

## 为什么保留回退

wheel 构建（MANIFEST.in 不再携带 file-backed SKILL.md）后，
`all_skills/` 仅服务于裸 `pip install` 的懒加载兜底；本地开发与
`octopus_runtime sync` 一律走 `skills/public/`。

## 相关门禁

- `tools/lint/skill_cross_dir_check.py --strict` —— 重叠数量 ratchet
- `tools/lint/skill_dedup_check.py` —— 技能内容去重基线
