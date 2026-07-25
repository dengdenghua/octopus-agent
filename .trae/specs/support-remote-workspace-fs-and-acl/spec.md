# 扩展 FS 端点支持远程 Workspace + Workspace 级 ACL Spec

## Why
当前 FS 端点（`/api/fs/{tree,read,write}`）只能访问服务器本地文件系统，无法访问通过 6 种 MountBackend 适配器（local / sftp / webdav / smb / nfs / s3）挂载的远程 Workspace。同时，缺少 Workspace 级别的访问控制——任何能访问 FS 端点的调用者都能读写整个挂载，无法按成员角色（owner / editor / reviewer / viewer）做差异化授权。

本变更在保持本地路径端点向后兼容的前提下，为 FS 端点加上：
1. `workspace_id:/path/to/file` 路径前缀解析，将远程 Workspace 请求路由到对应 MountBackend；
2. Workspace 级 ACL（基于 `WorkspaceStore.get_member_role`）；
3. 写操作的 FileLease 互斥保护（409 冲突 + 自动获取）；
4. 写成功后向绑定的 cowork 群组 blackboard 广播 `file_written` 事件；
5. `ContextGrant` 按角色自动设置（owner/editor → all，reviewer → from_join，viewer → summary）。

## What Changes
- **修改** `runtime/sensing/gateway/fs_router.py`：扩展 `create_fs_router()` 签名，新增 `workspace_store` / `lease_store` / `mount_registry` / `group_store` 4 个可选依赖；新增 `_parse_workspace_path` / `_resolve_remote_workspace` / `_remote_backend_for` / `_extract_user_id` / `_check_acl` / `_check_lease_conflict_or_acquire` / `_broadcast_file_written` / `_dir_entry_to_tree` / `_tree_depth_of` / `_is_ignored_remote_dir` 等内部 helper；将 `/api/fs/{tree,read,write}` 改为 async，识别 `workspace_id:` 前缀并走 MountBackend 分支；本地路径回退保持原行为。
- **修改** `runtime/workspace/cowork_bridge.py`：新增 `grant_for_workspace_role()`（角色 → ContextGrant 映射）和 `broadcast_file_written()`（写成功后向 cowork blackboard 追加 `file_written` 事件）；`sync_workspace_members_to_group()` 在 invite 事件中携带 `grant=grant_for_workspace_role(role)`。
- **新增** `tests/test_fs_remote_workspace.py`：12 个测试覆盖远程 read/write/tree、lease 冲突 409、lease 自动获取、同 holder 续约、无 holder_id 跳过 lease、广播 `file_written`、累积广播、向后兼容。
- **新增** `tests/test_workspace_acl.py`：21+ 测试覆盖 owner/editor/reviewer/viewer 各角色的读写权限、非成员 403、缺失 user_id 403、user_id 三种来源（query/header/body）、`grant_for_workspace_role` 全角色映射、`link_workspace_to_group` 自动设置 grant、`broadcast_file_written` 追加/累积/无 thread_id 静默。

## Impact
- **Affected specs**：FS 端点契约、Workspace 成员角色契约、Cowork Group ContextGrant 契约
- **Affected code**：
  - `runtime/sensing/gateway/fs_router.py`（核心修改）
  - `runtime/workspace/cowork_bridge.py`（新增 2 个导出函数）
  - `runtime/platform/ui/app.py`（create_fs_router 调用点未来需要补传新依赖——本次未改动）
  - `tests/test_fs_remote_workspace.py`（新增）
  - `tests/test_workspace_acl.py`（新增）
  - `tests/test_app_fs_endpoints.py`（既有——必须保持通过）

## ADDED Requirements

### Requirement: 远程 Workspace 路径解析
系统 SHALL 接受 `workspace_id:/path/to/file` 形式的路径参数，从中解析出 `workspace_id` 和相对路径，并路由到对应 Workspace 的 MountBackend。
- Windows 盘符（如 `C:/Users/...`）SHALL NOT 被识别为 workspace 前缀。
- 未知 `workspace_id`（未在 `workspace_store` 注册）SHALL 回退到本地路径解析器（向后兼容）。
- 未传 `workspace_store` 或 `mount_registry` 时，SHALL 完全保留原有本地路径行为。

#### Scenario: 远程读
- **WHEN** 调用 `GET /api/fs/read?path=ws-1:src/main.py&user_id=alice`
- **AND** `ws-1` 是已注册的 Workspace，`alice` 是其成员
- **THEN** 系统通过 `MountBackend.read_file("src/main.py")` 读取并返回内容
- **AND** 响应 `path` 字段为 `ws-1:src/main.py`

#### Scenario: 远程写
- **WHEN** 调用 `POST /api/fs/write` body 包含 `path=ws-1:src/app.py`、`content`、`holder_id=alice`
- **THEN** 系统通过 `MountBackend.write_file("src/app.py", bytes)` 写入
- **AND** 响应 `path` 字段为 `ws-1:src/app.py`

#### Scenario: 远程目录树
- **WHEN** 调用 `GET /api/fs/tree?path=ws-1:/&depth=1&user_id=alice`
- **THEN** 系统通过 `MountBackend.list_dir("/", 1)` 列出
- **AND** 过滤 `.git` / `node_modules` / `.octopus` / `logs` 目录

### Requirement: Workspace 级 ACL
系统 SHALL 对所有远程 Workspace 操作执行 ACL 检查：
- 写操作（`/api/fs/write`）要求 `owner` 或 `editor` 角色，否则 403
- 读操作（`/api/fs/read`、`/api/fs/tree`）要求任意成员角色，否则 403
- `user_id` 来源优先级：`?user_id=` 查询参数 → `X-User-Id` 请求头 → body 的 `user_id` 字段（POST only）
- ACL 检查失败时响应 body 的 `detail.error` 字段为：`workspace_store_not_configured` / `user_id_required` / `not_a_member` / `write_requires_editor`

#### Scenario: 非成员被拒
- **WHEN** 用户 `stranger` 调用 `GET /api/fs/read?path=ws-1:a.txt&user_id=stranger`
- **AND** `stranger` 不是 `ws-1` 的成员
- **THEN** 系统返回 403，`detail.error == "not_a_member"`

#### Scenario: reviewer 写被拒
- **WHEN** 角色 `reviewer` 的 `carol` 调用 `POST /api/fs/write` 写 `ws-1:a.txt`
- **THEN** 系统返回 403，`detail.error == "write_requires_editor"`，`detail.role == "reviewer"`
- **AND** 文件未被写入

### Requirement: FileLease 互斥保护
系统 SHALL 在远程 `/api/fs/write` 调用时执行 lease 检查：
- 若 `holder_id` 为空：跳过 lease 检查（向后兼容）
- 若存在其他 holder 持有的 exclusive lease：返回 409，`detail.error == "lease_conflict"`，文件不被写入
- 若无冲突：自动获取（或续约）exclusive lease（TTL 1800s）

#### Scenario: lease 冲突
- **WHEN** `bob` 持有 `ws-1:src/app.py` 的 exclusive lease
- **AND** `alice` 调用 write 携带 `holder_id=alice`
- **THEN** 系统返回 409，`detail.holder_id == "bob"`，`MountBackend.write_file` 未被调用

### Requirement: 写成功广播 file_written
系统 SHALL 在远程 write 成功后，若 `group_store` 和 `thread_id` 均已提供，向对应 cowork 群组的 blackboard 追加一条 `file_written` 事件，结构为：
```json
{"file_path": "...", "writer_id": "...", "ts": 1234567890.0, "workspace_id": "..."}
```
- 多次写入 SHALL 累积为列表（不覆盖）
- 缺少 `thread_id` 或 `group_store` 时 SHALL 静默跳过
- 广播失败 SHALL NOT 影响 write 响应

### Requirement: ContextGrant 按角色映射
`runtime.workspace.cowork_bridge.grant_for_workspace_role(role)` SHALL 返回：
- `owner` / `editor` → `ContextGrant(scope="all")`
- `reviewer` → `ContextGrant(scope="from_join")`
- `viewer` 或未知 → `ContextGrant(scope="summary")`（fail-safe）

`link_workspace_to_group()` 在 invite 事件中 SHALL 携带 `grant=grant_for_workspace_role(member.role)`。

## MODIFIED Requirements

### Requirement: create_fs_router 签名
`create_fs_router()` 新增 4 个可选 kwargs：`workspace_store`、`lease_store`、`mount_registry`、`group_store`。未传时保持原有本地路径行为完全不变（向后兼容）。

### Requirement: sync_workspace_members_to_group
在为 workspace 成员生成 `invite` MemberEvent 时，必须携带 `grant=grant_for_workspace_role(role)`，使新加入成员的可见历史范围按角色差异化。
