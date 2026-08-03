# Checklist

## 第一批验证
- [ ] `browser_desktop_repair_recipes.py` < 1000 行
- [ ] `llm_planner.py` < 1000 行
- [ ] `realtime_event_bridge.py` < 1000 行
- [ ] `realtime_team_stream.py` < 1000 行
- [ ] `openai_compat_providers.py` < 1000 行
- [ ] 第一批 5 个文件 ruff lint 通过
- [ ] 第一批相关测试全部通过
- [ ] `god_files_baseline.txt` 移除第一批 5 个条目
- [ ] 文档重生通过 `test_auto_docs_fresh.py`

## 第二批验证
- [ ] `agents_local_partner.py` < 1000 行
- [ ] `bridge.py` < 1000 行
- [ ] `agent_world_router.py` < 1000 行
- [ ] `evolution_router.py` < 1000 行
- [ ] `gepa_bridge.py` < 1000 行
- [ ] `fs_router.py` < 1000 行
- [ ] `browser_skills.py` < 1000 行
- [ ] `channels_router.py` < 1000 行
- [ ] 第二批 8 个文件 ruff lint 通过
- [ ] 第二批相关测试全部通过
- [ ] `god_files_baseline.txt` 移除第二批 8 个条目
- [ ] 文档重生通过

## 第三批验证
- [ ] `task_supervisor.py` < 1000 行
- [ ] `react_context.py` < 1000 行
- [ ] `react_prompt_assembly.py` < 1000 行
- [ ] `controller.py` < 1000 行
- [ ] `mount_backend.py` < 1000 行
- [ ] `health_router.py` < 1000 行
- [ ] `orchestrator.py` < 1000 行
- [ ] `journal.py` < 1000 行
- [ ] `config_router.py` < 1000 行
- [ ] `cli.py` < 1000 行
- [ ] 第三批 10 个文件 ruff lint 通过
- [ ] 第三批相关测试全部通过
- [ ] `god_files_baseline.txt` 移除第三批 10 个条目
- [ ] 文档重生通过

## 第四批验证
- [ ] `team_tasks_router.py` < 1000 行
- [ ] `observability_router.py` < 1000 行
- [ ] `browser_router.py` < 1000 行
- [ ] `meta_router.py` < 1000 行
- [ ] `chat_page.py` < 1000 行
- [ ] `agents_router.py` < 1000 行
- [ ] `realtime_cerebrum.py` < 1000 行
- [ ] `executor.py` < 1000 行
- [ ] `reflex_admin_router.py` < 1000 行
- [ ] 第四批 9 个文件 ruff lint 通过
- [ ] 第四批相关测试全部通过
- [ ] `god_files_baseline.txt` 移除第四批 9 个条目
- [ ] 文档重生通过

## 第五批验证
- [ ] `react_execution.py` < 1000 行
- [ ] `react_guards.py` < 1000 行
- [ ] `write_skills.py` < 1000 行
- [ ] `trace_store.py` < 1000 行
- [ ] `app.py` < 1000 行
- [ ] `react_parsing.py` < 1000 行
- [ ] `delegation_skills.py` < 1000 行
- [ ] `tool_bridge.py` < 1000 行
- [ ] 第五批 8 个文件 ruff lint 通过
- [ ] 第五批相关测试全部通过
- [ ] `god_files_baseline.txt` 为空或仅含注释
- [ ] 文档重生通过

## 全局验证
- [ ] `test_orphan_module_check.py` 通过
- [ ] `test_auto_docs_fresh.py` 通过
- [ ] 全量测试套件无回归
- [ ] 公开 API 向后兼容（无 import 错误）
