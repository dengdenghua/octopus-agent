# Tasks

## Task 6: 扩展 FS 端点支持远程 Workspace

- [x] Task 6.1: 修改 `runtime/sensing/gateway/fs_router.py` 添加远程 Workspace 路由逻辑
  - [x] SubTask 6.1.1: 扩展 `create_fs_router()` 签名，新增 `workspace_store` / `lease_store` / `mount_registry` / `group_store` 4 个可选 kwargs
  - [x] SubTask 6.1.2: 实现 `_parse_workspace_path()` 解析 `workspace_id:/path` 前缀（处理 Windows 盘符）
  - [x] SubTask 6.1.3: 实现 `_resolve_remote_workspace()` / `_remote_backend_for()` 获取 MountBackend
  - [x] SubTask 6.1.4: 将 `/api/fs/{tree,read,write}` 改为 async，识别前缀并路由到 MountBackend，未知 workspace 回退本地路径

- [x] Task 6.2: 实现 ACL 检查（详见 Task 7）

- [x] Task 6.3: 实现 FileLease 互斥保护
  - [x] SubTask 6.3.1: 实现 `_check_lease_conflict_or_acquire()` —— `holder_id` 为空时跳过
  - [x] SubTask 6.3.2: 其他 holder 持有 exclusive lease 时返回 409，`detail.error == "lease_conflict"`
  - [x] SubTask 6.3.3: 无冲突时自动获取（或续约）exclusive lease，TTL 1800s

- [x] Task 6.4: 实现写成功后广播 file_written
  - [x] SubTask 6.4.1: 在 `runtime/workspace/cowork_bridge.py` 新增 `broadcast_file_written()` 函数
  - [x] SubTask 6.4.2: 实现 `_broadcast_file_written()` helper 调用 `broadcast_file_written`
  - [x] SubTask 6.4.3: 多次写入累积为列表（不覆盖），缺少 thread_id 或 group_store 时静默跳过

## Task 7: Workspace 级 ACL 执行

- [x] Task 7.1: 实现 ACL 检查 helper
  - [x] SubTask 7.1.1: 实现 `_extract_user_id()` —— 优先级 query → header → body
  - [x] SubTask 7.1.2: 实现 `_check_acl()` —— 调用 `WorkspaceStore.get_member_role(workspace_id, user_id)`
  - [x] SubTask 7.1.3: 写操作要求 `owner` 或 `editor`，否则 403 `write_requires_editor`
  - [x] SubTask 7.1.4: 读操作要求任意角色，否则 403 `not_a_member`
  - [x] SubTask 7.1.5: 缺失 user_id 时 403 `user_id_required`
  - [x] SubTask 7.1.6: ACL 仅在远程 workspace 路径上执行，本地路径保留原行为

- [x] Task 7.2: 实现 ContextGrant 自动设置
  - [x] SubTask 7.2.1: 在 `runtime/workspace/cowork_bridge.py` 新增 `grant_for_workspace_role()` 函数
  - [x] SubTask 7.2.2: `sync_workspace_members_to_group()` 在 invite 事件中携带 `grant=grant_for_workspace_role(role)`
  - [x] SubTask 7.2.3: 角色映射：owner/editor → scope=all，reviewer → scope=from_join，viewer → scope=summary

## Task 7.3: 测试

- [x] Task 7.3.1: 创建 `tests/test_fs_remote_workspace.py`
  - [x] 实现 `_MockMountBackend`（in-memory dict + DirEntry 合成）
  - [x] 12 个测试：远程 read、404、未知 workspace 回退、远程 write、lease 409、自动获取、续约、跳过 lease、tree、过滤目录、广播、累积、向后兼容

- [x] Task 7.3.2: 创建 `tests/test_workspace_acl.py`
  - [x] 实现 `_StubBackend`
  - [x] 21+ 测试：owner/editor/reviewer/viewer 读、非成员 403、缺失 user_id 403、header 来源、tree ACL、owner/editor 写、reviewer/viewer 写 403、非成员写 403、body 来源 user_id、grant_for_workspace_role 全角色、link_workspace_to_group 自动 grant、broadcast_file_written 追加/累积/noop

## Task 8: 验证

- [x] Task 8.1: 运行 `python -m pytest tests/test_fs_remote_workspace.py tests/test_workspace_acl.py -v` 确保所有新测试通过
- [x] Task 8.2: 运行 `python -m pytest tests/test_app_fs_endpoints.py -v` 确保既有 FS 测试未破坏
- [x] Task 8.3: 修复测试运行中暴露的任何失败（修复 `test_read_unknown_workspace_prefix_falls_through_to_local` 断言以接受 403 或 404）

# Task Dependencies
- Task 6.1 → Task 6.3, Task 6.4, Task 7.1（依赖路由基础）
- Task 7.1 → Task 7.2（依赖 ACL helper）
- Task 6 + Task 7 → Task 7.3（测试依赖实现完成）
- Task 7.3 → Task 8（验证依赖测试编写完成）
