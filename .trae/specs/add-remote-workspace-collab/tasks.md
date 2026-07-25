# Tasks

## Phase 1: 后端基础设施

- [x] Task 1: 创建 Workspace 数据模型与存储层
  - [x] SubTask 1.1: 在 `runtime/workspace/` 新建模块，定义 `Workspace`、`WorkspaceMember` 数据类
  - [x] SubTask 1.2: 实现 `WorkspaceStore`（SQLite），表结构：`workspaces(id, name, mount_type, mount_target, mount_options_json, owner_id, created_at)`、`workspace_members(workspace_id, member_id, role, added_at)`
  - [x] SubTask 1.3: 凭据加密存储（复用 `runtime/safety/` 现有加密工具，mount_options 中的敏感字段加密）
  - [x] SubTask 1.4: 编写单元测试 `tests/test_workspace_store.py`

- [x] Task 2: 实现 MountBackend 抽象层
  - [x] SubTask 2.1: 在 `runtime/sensing/server/mount_backend.py` 定义 `MountBackend` 抽象基类：`read_file/write_file/list_dir/stat/mkdir/remove/test_connection`
  - [x] SubTask 2.2: 实现 `LocalMountBackend`（包装现有 `LocalBackend` 的路径白名单逻辑）
  - [x] SubTask 2.3: 实现 `SftpMountBackend`（基于 paramiko SFTPClient，复用 `SshBackend` 的连接配置）
  - [x] SubTask 2.4: 实现 `WebdavMountBackend`（基于 webdav3 库或纯 HTTP，支持 Nextcloud/坚果云/CD2）
  - [x] SubTask 2.5: 实现 `SmbMountBackend`（基于 smbprotocol 库）
  - [x] SubTask 2.6: 实现 `S3MountBackend`（基于 boto3，支持 MinIO/AWS/阿里云 OSS）
  - [x] SubTask 2.7: 实现 `MountBackendRegistry`：按 `mount_type` 路由到对应适配器
  - [x] SubTask 2.8: 编写单元测试 `tests/test_mount_backend.py`（每个适配器至少覆盖 read/write/list）

- [x] Task 3: 实现文件租约机制
  - [x] SubTask 3.1: 在 `runtime/platform/io/lease.py` 定义 `FileLease` 数据类：`lease_id, workspace_id, file_path, holder_id, acquired_at, expires_at, kind(exclusive/shared)`
  - [x] SubTask 3.2: 实现 `LeaseStore`（SQLite）：`acquire/renew/release/get_by_path/get_by_holder/cleanup_expired`
  - [x] SubTask 3.3: 复用 `atomic.py` 的 `_cross_process_lock` 做瞬态写锁，持久租约由 `LeaseStore` 管理
  - [x] SubTask 3.4: 后台线程定期清理过期租约（复用 `runtime/core/hearts/` 心跳机制）
  - [x] SubTask 3.5: 编写单元测试 `tests/test_file_lease.py`（acquire/conflict/renew/expire/release）

- [x] Task 4: 实现 Workspace HTTP API
  - [x] SubTask 4.1: 在 `runtime/sensing/gateway/workspaces_router.py` 实现 CRUD 端点：`POST /api/workspaces`、`GET /api/workspaces`、`GET /api/workspaces/{id}`、`DELETE /api/workspaces/{id}`
  - [x] SubTask 4.2: 实现成员管理端点：`POST /api/workspaces/{id}/members`、`DELETE /api/workspaces/{id}/members/{mid}`、`GET /api/workspaces/{id}/members`
  - [x] SubTask 4.3: 实现租约端点：`POST /api/workspaces/{id}/lease`、`DELETE /api/workspaces/{id}/lease/{lid}`、`POST /api/workspaces/{id}/lease/{lid}/renew`
  - [x] SubTask 4.4: 实现挂载点健康检查：`POST /api/workspaces/{id}/health`
  - [x] SubTask 4.5: 添加 `ui.remote_workspace` feature flag 灰度控制
  - [x] SubTask 4.6: 编写 API 测试 `tests/test_workspaces_router.py`

## Phase 2: 协作集成

- [x] Task 5: Workspace ↔ Cowork Group 绑定
  - [x] SubTask 5.1: 在 `runtime/memory/cowork/group.py` 的 `MemberEvent` 中新增 `workspace_link` 事件类型
  - [x] SubTask 5.2: 在 `CollaborationSession.resolve_session()` 中折叠 workspace 绑定信息
  - [x] SubTask 5.3: workspace 成员变更自动同步到 cowork group 花名册（owner→participant, viewer→observer）
  - [x] SubTask 5.4: 编写集成测试 `tests/test_workspace_cowork_bind.py`

- [x] Task 6: 扩展 FS 端点支持远程 workspace
  - [x] SubTask 6.1: 在 `fs_router.py` 中根据 `workspace_path` 前缀路由到 `MountBackendRegistry`
  - [x] SubTask 6.2: `/api/fs/read`、`/api/fs/write`、`/api/fs/tree` 支持远程路径
  - [x] SubTask 6.3: `/api/fs/write` 前检查文件租约，无租约或租约不匹配返回 409
  - [x] SubTask 6.4: 写入成功后广播 `file_written` 事件到 cowork group
  - [x] SubTask 6.5: 编写集成测试 `tests/test_fs_remote_workspace.py`

- [x] Task 7: Workspace 级 ACL 执行
  - [x] SubTask 7.1: 在 FS 端点中间件中根据 `workspace_id` 查询请求者角色
  - [x] SubTask 7.2: owner/editor 可读写（写需租约），reviewer 只读+可评论，viewer 只读
  - [x] SubTask 7.3: 复用 `ContextGrant` 做 workspace 文件访问授权面
  - [x] SubTask 7.4: 编写 ACL 测试 `tests/test_workspace_acl.py`

## Phase 3: 前端 UI

- [x] Task 8: WorkspaceSwitcher 组件
  - [x] SubTask 8.1: 在 `frontend/src/components/workspace/workspace-switcher.tsx` 实现切换器：列表/搜索/置顶
  - [x] SubTask 8.2: 调用 `/api/workspaces` 加载列表，切换时更新当前线程 `workspace_id`
  - [x] SubTask 8.3: 显示 workspace 类型图标（local/smb/nfs/webdav/sftp/s3）
  - [x] SubTask 8.4: 集成到 workspace-sidebar.tsx 顶部

- [x] Task 9: MountPointDialog 组件
  - [x] SubTask 9.1: 在 `frontend/src/components/workspace/mount-point-dialog.tsx` 实现添加挂载点对话框
  - [x] SubTask 9.2: 协议选择（local/smb/nfs/webdav/sftp/s3），根据协议动态显示字段
  - [x] SubTask 9.3: 连接测试按钮（调用 `/api/workspaces/{id}/health`）
  - [x] SubTask 9.4: 凭据字段加密传输（HTTPS + 前端不持久化明文）

- [x] Task 10: WorkspaceMembersPanel 组件
  - [x] SubTask 10.1: 在 `frontend/src/components/workspace/workspace-members-panel.tsx` 实现成员面板
  - [x] SubTask 10.2: 显示成员头像、角色、在线状态（复用 PresenceStore 数据）
  - [x] SubTask 10.3: 角色管理（owner 可修改他人角色）
  - [x] SubTask 10.4: 显示每人当前编辑的文件（从 FileLease 查询）

- [x] Task 11: FileLeaseIndicator 组件
  - [x] SubTask 11.1: 在 `frontend/src/components/workspace/file-lease-indicator.tsx` 实现租约标识
  - [x] SubTask 11.2: 文件树中被锁定的文件显示持有者头像 + 剩余时间
  - [x] SubTask 11.3: hover 显示「请求接管」按钮

- [x] Task 12: 扩展 WorkDirSelector
  - [x] SubTask 12.1: 在 `workdir-selector.tsx` 新增「远程挂载点」Tab，从 Workspace 注册表加载
  - [x] SubTask 12.2: 选择远程 workspace 后设置 `workspace_id` 而非 `workspace_path`

## Phase 4: 验证

- [x] Task 13: 端到端测试
  - [x] SubTask 13.1: `tests/test_workspace_e2e.py` — 注册 NAS 挂载 → 添加成员 → 协作编辑 → 租约冲突 → 合并
  - [x] SubTask 13.2: `frontend/e2e/workspace-collab.spec.ts` — Playwright e2e：两人同时打开 workspace，文件树实时同步，租约标识显示

- [x] Task 14: 类型检查与 lint
  - [x] SubTask 14.1: 后端 `pytest tests/test_workspace_*.py tests/test_mount_backend.py tests/test_file_lease.py` 全通过
  - [x] SubTask 14.2: 前端 `pnpm typecheck` + `pnpm eslint` + `pnpm vitest run` 全通过

# Task Dependencies
- [Task 2] depends on [Task 1]（MountBackend 需要 Workspace 实体的 mount_type）
- [Task 3] 独立，可与 Task 1/2 并行
- [Task 4] depends on [Task 1] + [Task 2] + [Task 3]
- [Task 5] depends on [Task 1]
- [Task 6] depends on [Task 2] + [Task 3] + [Task 4]
- [Task 7] depends on [Task 4] + [Task 5]
- [Task 8-12] depends on [Task 4]（前端需要 API 就绪）
- [Task 13] depends on [Task 6] + [Task 7] + [Task 12]
- [Task 14] depends on [Task 13]
