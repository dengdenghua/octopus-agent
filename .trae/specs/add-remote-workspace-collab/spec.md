# 远程工作空间协作 Spec

## Why

当前 Octopus 的「工作空间」只是线程元数据中的一个本地路径字符串，无法满足「NAS/云盘挂载目录 + 多人远程协作」的场景。用户希望像 CD2/云盘那样直接挂载远程目录作为工作空间，选择该空间后多人（含 Agent）可远程协作完成项目，形成「GitHub + NAS/云盘 + AI 协作工作台」的体验。

现有 cowork（协作会话/presence/异步任务/Team Room）和原子文件 IO 已成熟，但缺少：workspace 一等公民实体、远程文件系统抽象、文件租约、workspace 级 ACL、挂载点注册 UI。

## What Changes

### 后端
- 新增 `Workspace` 一等实体（SQLite 表）：`workspace_id, name, mount_type, mount_target, mount_options, owner_id, created_at`
- 新增 `WorkspaceMember` 表：`workspace_id, member_id, role(owner/editor/reviewer/viewer), added_at`
- 新增 `MountBackend` 抽象层：统一 `local / smb / nfs / webdav / sftp / s3` 挂载访问，提供 `read_file/write_file/list_dir/stat/mkdir/remove` 文件级 API
- 新增 `FileLease` 持久租约机制：基于 `atomic.py` 的跨进程锁扩展为带 TTL 的持久锁，防多人静默覆盖
- 新增 Workspace CRUD HTTP API：`/api/workspaces`（POST/GET/DELETE）、`/api/workspaces/{id}/members`、`/api/workspaces/{id}/lease`
- 复用 `CollaborationSession` + `GroupStore` + `PresenceStore`，通过 `workspace_link` 事件（类似 `room_link`）把 workspace 与 cowork group 双向绑定
- 复用 `ContextGrant` 做 workspace 文件访问授权面

### 前端
- 新增 `WorkspaceSwitcher` 组件：列出已注册 workspace，支持切换/搜索/置顶
- 扩展 `WorkDirSelector`：除「本地目录」外增加「远程挂载点」入口，支持添加 SMB/NFS/WebDAV/SFTP/S3 挂载
- 新增 `WorkspaceMembersPanel` 组件：成员列表、角色管理、在线状态、当前编辑文件
- 新增 `FileLeaseIndicator` 组件：文件树中显示被他人锁定的文件，hover 显示租约持有者与剩余时间
- 新增 `MountPointDialog` 组件：添加挂载点（协议类型、地址、凭据、挂载选项）

### 配置
- 新增 `ui.remote_workspace` feature flag（默认 off，灰度开启）
- 新增 `workspace.mount_backends` 配置段：启用哪些协议适配器

## Impact

- **Affected specs**: cowork 协作协议、projectos 项目编排、fs 文件端点、remote_transport 远程后端
- **Affected code**:
  - `runtime/memory/cowork/` — 新增 `workspace_link` 事件类型、workspace↔group 绑定
  - `runtime/platform/io/atomic.py` — 扩展 `_cross_process_lock` 为持久 TTL 租约
  - `runtime/sensing/gateway/` — 新增 `workspaces_router.py`、扩展 `fs_router.py` 支持远程路径
  - `runtime/sensing/server/` — 新增 `mount_backend.py` 抽象层与各协议适配器
  - `frontend/src/components/workspace/` — 新增 WorkspaceSwitcher/MountPointDialog/WorkspaceMembersPanel/FileLeaseIndicator
  - `frontend/src/components/workspace/workdir-selector.tsx` — 扩展远程挂载入口

## ADDED Requirements

### Requirement: Workspace 一等实体
系统 SHALL 提供独立的 Workspace 实体，支持注册、查询、删除，每个 workspace 绑定一个挂载点（local/smb/nfs/webdav/sftp/s3）。

#### Scenario: 注册 NAS 挂载工作空间
- **WHEN** 用户通过 MountPointDialog 选择 SMB 协议，填入 `smb://nas.local/projects` 和凭据
- **THEN** 系统创建 Workspace 记录，验证挂载点可访问，返回 `workspace_id`
- **AND** 该 workspace 出现在 WorkspaceSwitcher 列表中

#### Scenario: 切换工作空间
- **WHEN** 用户在 WorkspaceSwitcher 中选择另一个 workspace
- **THEN** 当前线程的 `workspace_path` 更新为该 workspace 的挂载路径
- **AND** 文件树、Agent 工作目录、FS 端点全部切换到新 workspace

### Requirement: 远程文件系统抽象层
系统 SHALL 提供 `MountBackend` 抽象层，统一 local/smb/nfs/webdav/sftp/s3 六种协议，暴露 `read_file/write_file/list_dir/stat/mkdir/remove` 文件级 API。

#### Scenario: 通过 WebDAV 访问云盘文件
- **WHEN** Agent 请求读取 workspace 内文件 `report.md`
- **THEN** 系统通过 WebDAV 适配器发起 `GET` 请求获取文件内容
- **AND** 对用户和 Agent 透明，API 与本地文件操作一致

#### Scenario: SFTP 写入远程文件
- **WHEN** Agent 通过 `/api/fs/write` 写入 SFTP workspace 内文件
- **THEN** 系统通过 SFTP 适配器上传文件
- **AND** 写入完成后触发 `file_written` 协作事件通知在线成员

### Requirement: 文件租约机制
系统 SHALL 提供带 TTL 的持久文件租约，防止多人同时编辑同一文件导致静默覆盖。

#### Scenario: 获取文件租约
- **WHEN** 用户 Alice 开始编辑 `config.yaml`
- **THEN** 系统为 Alice 创建 30 分钟 TTL 的租约
- **AND** 文件树中该文件对其他成员显示「Alice 正在编辑」标识

#### Scenario: 租约冲突
- **WHEN** 用户 Bob 尝试编辑已被 Alice 锁定的 `config.yaml`
- **THEN** 系统返回 409 Conflict，提示「Alice 正在编辑，剩余 23 分钟」
- **AND** Bob 可选择「请求接管」或「等待」

#### Scenario: 租约过期自动释放
- **WHEN** Alice 的租约 TTL 到期且未续约
- **THEN** 系统自动释放租约
- **AND** 文件恢复为可编辑状态

### Requirement: Workspace 级 ACL
系统 SHALL 把 workspace 与 cowork group 绑定，按成员角色（owner/editor/reviewer/viewer）控制文件读写权限。

#### Scenario: Viewer 只读权限
- **WHEN** 角色为 viewer 的 Bob 尝试通过 `/api/fs/write` 写入文件
- **THEN** 系统返回 403 Forbidden
- **AND** Bob 的文件树显示为只读

#### Scenario: Editor 编辑权限
- **WHEN** 角色为 editor 的 Carol 写入文件
- **THEN** 系统允许写入（需先获取租约）
- **AND** 写入事件广播到 workspace 的所有在线成员

### Requirement: 多人远程协作面板
系统 SHALL 在 workspace 页面显示在线成员、正在编辑的文件、待合并变更和 Agent 执行状态。

#### Scenario: 查看协作面板
- **WHEN** 用户打开 workspace 页面
- **THEN** 右侧面板显示：在线成员头像（含 Agent）、每人当前编辑的文件、未读任务、待合并的 Git 变更
- **AND** 成员离线时头像变灰

### Requirement: 挂载点管理 UI
系统 SHALL 提供 MountPointDialog 组件，支持添加/编辑/删除远程挂载点。

#### Scenario: 添加 S3 挂载点
- **WHEN** 用户在 MountPointDialog 选择 S3 协议，填入 endpoint/bucket/access_key/secret_key
- **THEN** 系统验证连接，保存挂载配置（凭据加密存储）
- **AND** 挂载点立即可用作 workspace

## MODIFIED Requirements

### Requirement: 工作空间选择
当前 WorkDirSelector 仅支持本地目录选择。扩展为支持「本地目录」和「远程挂载点」两种入口，远程挂载点从 Workspace 注册表加载。

### Requirement: 文件系统端点
当前 `/api/fs/*` 端点仅支持本地路径。扩展为根据 `workspace_path` 前缀路由到对应 `MountBackend`，远程 workspace 的文件操作通过对应协议适配器执行。

### Requirement: 协作会话绑定
当前 `CollaborationSession` 通过 `room_link` 事件绑定 Team Room。新增 `workspace_link` 事件类型，把 workspace 与 cowork group 双向绑定，使 workspace 成员自动同步到 group 花名册。

## REMOVED Requirements

### Requirement: workspace_path 作为纯字符串元数据
**Reason**: workspace 需要一等实体支撑 ACL/租约/成员/挂载类型，纯字符串无法承载
**Migration**: 新增 Workspace 表后，thread metadata 中的 `workspace_path` 改为存储 `workspace_id`，兼容期内同时保留 `workspace_path` 字符串字段用于回退
