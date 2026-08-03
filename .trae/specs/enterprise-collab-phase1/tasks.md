# Tasks

- [x] Task 1: 组织/部门/频道数据模型
  - [x] SubTask 1.1: 新增 `runtime/workspace/org.py`（Organization / Department / Channel / OrgMember / ChannelMember，含 to_dict/from_dict 与角色辅助）
  - [x] SubTask 1.2: 新增 `runtime/workspace/org_store.py`（OrgStore SQLite 持久化，5 表 + 级联删除 + ACL 判定 + 按成员过滤频道）
  - [x] SubTask 1.3: 更新 `runtime/workspace/__init__.py` 导出
  - [x] SubTask 1.4: 新增 `tests/test_org_store.py`（40 用例，已验证通过）

- [x] Task 2: 组织 API 路由
  - [x] SubTask 2.1: 新增 `runtime/sensing/gateway/org_router.py`（create_org_router：组织/部门/频道/成员/ACL 的 CRUD + 查询）
  - [x] SubTask 2.2: 写操作按角色鉴权（组织管理员 / 频道管理员），非管理员 403
  - [x] SubTask 2.3: 在 `runtime/platform/ui/_app_routers.py` 挂载 org_router，注入 OrgStore 单例
  - [x] SubTask 2.4: 新增 `tests/test_org_router.py`（覆盖创建/查询/鉴权/403，11 用例通过）

- [x] Task 3: 频道即群聊（Agent 群聊 + 持久化消息）
  - [x] SubTask 3.1: 新增 `runtime/workspace/channel_bridge.py`（Channel ↔ GroupStore/RoomMessageStore 桥接）
  - [x] SubTask 3.2: 频道成员同步到 group 花名册（invite 事件），复用 fold_state 重建
  - [x] SubTask 3.3: 频道消息写入 RoomMessageStore，支持 history 恢复
  - [x] SubTask 3.4: 新增 `tests/test_channel_bridge.py`（覆盖成员同步、消息持久化、重启恢复，12 用例通过）

# Task Dependencies
- Task 2 依赖 Task 1（数据层已就绪）
- Task 3 依赖 Task 1（需复用 org 模型与 OrgStore）
- Task 2 与 Task 3 之间无强依赖，可并行