# Checklist

## 后端数据模型
- [x] Workspace 实体表已创建，包含 id/name/mount_type/mount_target/mount_options/owner_id/created_at 字段
- [x] WorkspaceMember 表已创建，包含 workspace_id/member_id/role/added_at 字段
- [x] mount_options 中的敏感字段（密码/token/secret_key）已加密存储
- [x] WorkspaceStore 的 CRUD 操作有单元测试覆盖

## MountBackend 抽象层
- [x] MountBackend 抽象基类定义了 read_file/write_file/list_dir/stat/mkdir/remove/test_connection 方法
- [x] LocalMountBackend 已实现并复用 LocalBackend 的路径白名单逻辑
- [x] SftpMountBackend 已实现，基于 paramiko SFTPClient
- [x] WebdavMountBackend 已实现，支持 Nextcloud/坚果云/CD2 等 WebDAV 服务
- [x] SmbMountBackend 已实现，基于 smbprotocol
- [x] S3MountBackend 已实现，支持 MinIO/AWS/阿里云 OSS
- [x] MountBackendRegistry 按 mount_type 正确路由到对应适配器
- [x] 每个适配器至少有 read/write/list 的单元测试

## 文件租约机制
- [x] FileLease 数据类包含 lease_id/workspace_id/file_path/holder_id/acquired_at/expires_at/kind 字段
- [x] LeaseStore 支持 acquire/renew/release/get_by_path/get_by_holder/cleanup_expired 操作
- [x] 租约冲突时返回 409 Conflict 并提示持有者与剩余时间
- [x] 租约 TTL 到期后自动释放
- [x] 后台清理线程定期清理过期租约

## Workspace HTTP API
- [x] POST /api/workspaces 可创建 workspace 并验证挂载点可访问
- [x] GET /api/workspaces 返回当前用户可访问的 workspace 列表
- [x] DELETE /api/workspaces/{id} 级联删除 workspace 及其成员记录
- [x] POST /api/workspaces/{id}/members 可添加成员并指定角色
- [x] POST /api/workspaces/{id}/lease 可获取文件租约
- [x] POST /api/workspaces/{id}/health 可验证挂载点连接状态
- [x] ui.remote_workspace feature flag 默认 off

## 协作集成
- [x] workspace_link 事件类型已添加到 MemberEvent
- [x] CollaborationSession.resolve_session() 可折叠 workspace 绑定信息
- [x] workspace 成员变更自动同步到 cowork group 花名册
- [x] /api/fs/read、/api/fs/write、/api/fs/tree 支持远程 workspace 路径
- [x] /api/fs/write 前检查文件租约，无租约或租约不匹配返回 409
- [x] 写入成功后广播 file_written 事件到 cowork group
- [x] ACL 按 owner/editor/reviewer/viewer 角色正确执行读写权限

## 前端 UI
- [x] WorkspaceSwitcher 组件可列出/搜索/切换 workspace
- [x] WorkspaceSwitcher 显示 workspace 类型图标
- [x] WorkspaceSwitcher 已集成到 workspace-sidebar.tsx 顶部
- [x] MountPointDialog 支持选择协议并动态显示字段
- [x] MountPointDialog 有连接测试按钮
- [x] WorkspaceMembersPanel 显示成员头像/角色/在线状态/当前编辑文件
- [x] FileLeaseIndicator 在文件树中显示被锁定文件的持有者和剩余时间
- [x] WorkDirSelector 新增「远程挂载点」Tab

## 端到端验证
- [x] 后端 e2e 测试：注册 NAS 挂载 → 添加成员 → 协作编辑 → 租约冲突 → 合并 全通过
- [x] 前端 Playwright e2e：两人同时打开 workspace，文件树实时同步，租约标识显示
- [x] 后端 pytest tests/test_workspace_*.py tests/test_mount_backend.py tests/test_file_lease.py 全通过
- [x] 前端 pnpm typecheck + pnpm eslint + pnpm vitest run 全通过
