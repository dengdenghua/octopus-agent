# Checklist

## 实现
- [x] `runtime/sensing/gateway/fs_router.py` 的 `create_fs_router()` 新增 `workspace_store` / `lease_store` / `mount_registry` / `group_store` 4 个可选 kwargs
- [x] `_parse_workspace_path()` 正确解析 `workspace_id:/path/to/file` 前缀，并跳过 Windows 盘符（`C:/...`）
- [x] `_resolve_remote_workspace()` 调用 `WorkspaceStore.get_workspace()`，未知 workspace 返回 None 回退本地路径
- [x] `_remote_backend_for()` 调用 `MountBackendRegistry.get_or_create()`，失败返回 None
- [x] `/api/fs/tree` / `/api/fs/read` / `/api/fs/write` 已改为 async，远程 workspace 走 MountBackend 分支
- [x] 本地路径分支完全保留原有 `_assert_in_scope` / `_assert_within_allowed_roots` 行为
- [x] `_check_lease_conflict_or_acquire()` 在 `holder_id` 为空时跳过；冲突时返回 409；无冲突时自动获取 TTL=1800s 的 exclusive lease
- [x] `_broadcast_file_written()` 在 `group_store` 或 `thread_id` 缺失时静默跳过；广播失败不影响 write 响应
- [x] `runtime/workspace/cowork_bridge.py` 新增 `grant_for_workspace_role()` 函数并加入 `__all__`
- [x] `runtime/workspace/cowork_bridge.py` 新增 `broadcast_file_written()` 函数并加入 `__all__`
- [x] `sync_workspace_members_to_group()` 在 invite 事件中携带 `grant=grant_for_workspace_role(role)`

## ACL 行为
- [x] 写操作要求 `owner` 或 `editor`，否则返回 403 + `detail.error == "write_requires_editor"` + `detail.role` + `detail.required`
- [x] 读操作要求任意成员角色，否则返回 403 + `detail.error == "not_a_member"` + `detail.user_id`
- [x] 缺失 user_id 返回 403 + `detail.error == "user_id_required"`
- [x] user_id 解析顺序：`?user_id=` query → `X-User-Id` header → body `user_id` 字段（POST only）
- [x] ACL 仅对远程 workspace 路径生效，本地路径保留原 `_assert_in_scope` 行为

## ContextGrant 映射
- [x] `grant_for_workspace_role("owner")` == `ContextGrant(scope="all")`
- [x] `grant_for_workspace_role("editor")` == `ContextGrant(scope="all")`
- [x] `grant_for_workspace_role("reviewer")` == `ContextGrant(scope="from_join")`
- [x] `grant_for_workspace_role("viewer")` == `ContextGrant(scope="summary")`
- [x] `grant_for_workspace_role("unknown")` == `ContextGrant(scope="summary")` (fail-safe)

## 广播 file_written
- [x] 写成功后向 blackboard 追加 `{"file_path", "writer_id", "ts", "workspace_id"}` 条目
- [x] 多次写入累积为列表（read → append → write）
- [x] 缺少 `thread_id` 时静默跳过
- [x] 缺少 `group_store` 时静默跳过
- [x] 广播异常不影响 write 响应

## 测试覆盖
- [x] `tests/test_fs_remote_workspace.py` 覆盖远程 read/write/tree、lease 409、自动获取、续约、跳过 lease、广播、累积、向后兼容（12 测试）
- [x] `tests/test_workspace_acl.py` 覆盖所有角色 × 读/写权限、非成员 403、缺失 user_id 403、三种 user_id 来源、grant 映射、link_workspace_to_group、broadcast_file_written（21+ 测试）

## 验证
- [x] `python -m pytest tests/test_fs_remote_workspace.py tests/test_workspace_acl.py -v` 全部通过（39 测试）
- [x] `python -m pytest tests/test_app_fs_endpoints.py -v` 全部通过（30 既有测试未破坏）
- [x] `python -m pytest tests/test_workspace_cowork_bind.py tests/test_workspace_api_router.py tests/test_workspace_store.py tests/test_workspaces_router.py -v` 全部通过（92 关联测试未破坏）
