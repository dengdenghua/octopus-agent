# 角色技能精简 — 2026-09-10

按岗位分配技能，取消 Eve 的全技能通配；本地仅保留岗位、共享及系统必备技能。

| 角色 | 数量 | 技能 |
| --- | ---: | --- |
| Eve — 办公统筹 | 7 | documents, pdf, presentations, spreadsheets, email-manager, work-report-expert, okr-planner |
| Kane — 应用研发 | 8 | frontend-ui-engineering, backend-building, typescript-best-practices, code-quality, code-vuln-audit, test-driven-dev, skill-creator, webapp-building |
| Raven — 自动化 | 5 | browser-use, browser-testing-with-devtools, documents, spreadsheets, pdf |
| Luna — 影视制作 | 7 | creative-visual-direction, creative-microdrama-writer, creative-storyboard-assets, creative-video-editor, creative-comfyui-workflow, seedance-video-generate, seedream-image-generate |
| Shion — 电商增长 | 6 | ad-creative, seo-audit, pricing-advisor, competitive-seo-intel, creative-ecommerce-images, chart-image |
| Noah — 投资研究 | 5 | equity-research, cn-finance-data, westock-data, stock-research-report-expert, chart-image |
| Zero — 学术研究 | 6 | academic-paper-expert, paper-writing, deep-research, auto-stat-test, pdf, chart-image |

系统管理员 Leon 保留 code-quality、code-vuln-audit、skill-creator。共享写作兜底保留 general-writer。

去重后本地 86 项，共 90 份 SKILL.md：39 项岗位/共享技能，43 项 Android/iOS 系统接口定义，以及 4 项其余内置技能；文档能力在内置插件和提示技能目录各有实体但仅统计一次。

清理前为 753 项。本次移除其余加载目录内的技能；完整可恢复备份位于 `.codex-run/role-skill-prune-20260910`。`move-plan.json` 记录原路径与归档路径；`restored_canonical_packages` 记录已恢复的规范包。角色原配置及锁文件也已备份。未清理 Codex 自身的技能目录。

验证：56 项后端测试通过；七个角色与系统管理员全部技能均能注册；Android 30、iOS 13 个接口加载正常。外部服务凭据和模型推理未逐项实调。

云端目录未删除；此前全量上云仅完成打包，仍未签名发布。本次精简针对本地安装与角色配置，不代表历史全部技能已上云。
