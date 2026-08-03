# Checklist

- [x] 组织/部门/频道数据模型：创建组织，owner 自动成为成员（role=owner）
- [x] 统一成员模型：同一张 org_members 表承载 Human 与 Agent（kind 区分）
- [x] 部门树：支持嵌套，跨组织父部门被拒绝
- [x] 频道 ACL：`can_access_channel` 单一判定入口，非成员不可见
- [x] 按成员过滤频道列表：`list_channels_for_user` 只返回有权限的频道
- [x] 组织管理员（owner/admin）可见本组织全部频道
- [x] 级联删除：删组织 → 部门/频道/成员；删频道 → ACL；删部门 → 挂载频道
- [x] 模型 dataclass 的 to_dict/from_dict 往返一致
- [x] `tests/test_org_store.py` 40 用例全部通过（已执行验证）
- [x] 组织 API 路由：创建/查询组织/部门/频道/成员/ACL 的 HTTP 接口已实现
- [x] API 写操作按角色鉴权：非组织管理员 / 非频道管理员对写操作返回 403
- [x] org_router 已挂载到应用装配点并注入 OrgStore 单例
- [x] `tests/test_org_router.py` 覆盖创建/查询/鉴权/403 并通过（11 用例）
- [x] 频道即群聊：频道成员同步到 GroupStore 花名册（invite 事件）
- [x] 频道消息写入 RoomMessageStore，重启后可通过 history() 恢复
- [x] `tests/test_channel_bridge.py` 覆盖成员同步、消息持久化、重启恢复并通过（12 用例）