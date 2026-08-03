# 企业协作主链 · 阶段一（Enterprise Collab Phase 1）Spec

## Why

Octopus 目前是「个人 Agent 工作系统」，身份是单机 `Identity` + JWT，无组织树、无企业频道、无统一成员模型。当需要升级为「同时连接个人电脑、本地数据和企业团队的 Agent 工作系统」时，第一道门槛是补齐企业协作主链的地基：**组织/部门/频道 + 统一成员 + 频道 ACL + Agent 群聊 + 持久化消息**。

本变更把阶段一完整落地，使「企业空间」可被真实使用——至少一个组织、若干频道、Agent 与 Human 同群聊、消息可持久化、基础权限生效。

## What Changes

### 数据层（已完成，作为本 spec 的既有基础）
- **新增** `runtime/workspace/org.py`：`Organization`（租户）、`Department`（部门树）、`Channel`（频道/群聊）、`OrgMember`/`ChannelMember`（统一成员模型，`kind` 区分 human/agent），含 `to_dict/from_dict` 与角色辅助函数。
- **新增** `runtime/workspace/org_store.py`：`OrgStore` SQLite 持久化，5 张表（organizations / departments / org_members / channels / channel_members），级联删除、ACL 判定、按成员过滤的频道列表。
- **修改** `runtime/workspace/__init__.py`：导出新模型与 `OrgStore`。

### API 层（本 spec 新增）
- **新增** `runtime/sensing/gateway/org_router.py`：`create_org_router()` 暴露组织/部门/频道/成员/ACL 的 HTTP 接口，所有写操作做组织管理员 / 频道管理员鉴权。
- **修改** `runtime/platform/ui/app.py`（或对应装配点）：挂载 `org_router`，注入 `OrgStore` 单例。

### 群聊接线（本 spec 新增）
- **新增** `runtime/workspace/channel_bridge.py`：把 `Channel` 与 `GroupStore`/`RoomMessageStore` 桥接，复用 `cowork_bridge` 的 `workspace_link` 模式，实现「频道即群聊」：频道成员 → group 花名册，频道路径 → 消息持久化。

### 权限（本 spec 新增）
- 频道级 ACL 在 API 层强制执行：非成员不可读频道内容（`can_access_channel` / `list_channels_for_user`），频道管理员可管理成员。

## Impact

- **Affected specs**：企业协作主链规划（docs/enterprise-collaboration-roadmap.md）、cowork 协作协议（`runtime/memory/cowork/`）、workspace 模块（`runtime/workspace/`）
- **Affected code**：
  - `runtime/workspace/org.py`、`org_store.py`（既有，本 spec 的验收基础）
  - `runtime/sensing/gateway/org_router.py`（新增，API 层）
  - `runtime/workspace/channel_bridge.py`（新增，群聊接线）
  - `runtime/platform/ui/app.py`（装配点）
  - `tests/test_org_store.py`（既有，40 用例）
  - `tests/test_org_router.py`、`tests/test_channel_bridge.py`（新增）

## ADDED Requirements

### Requirement: 组织 / 部门 / 频道数据模型
系统 SHALL 提供组织、部门、频道三层的持久化模型，支持创建组织、在组织下建部门（可嵌套）、在组织或部门下建频道。

#### Scenario: 创建组织并加入成员
- **WHEN** 管理员创建组织 `Acme`，owner 自动成为组织成员
- **THEN** 组织可被查询，owner 出现在 `org_members` 且角色为 `owner`
- **AND** 可通过 `list_organizations_for_user` 反查该成员所属组织

#### Scenario: 创建嵌套部门
- **WHEN** 管理员在组织 `Acme` 下创建 `Eng`，再在 `Eng` 下创建 `Backend`
- **THEN** 两部门均挂载在 `Acme`，`Backend.parent_id == Eng.id`
- **AND** 跨组织的父部门引用被拒绝（`ValueError`）

### Requirement: 统一成员模型（Human + Agent）
系统 SHALL 用同一张 `org_members` 表承载 Human 与 Agent，`kind` 字段区分；Agent 可携带 `display_name` 与角色。

#### Scenario: 同一身份体系可查 Human 与 Agent
- **WHEN** 组织加入 Human `u2` 与 Agent `agent-1`
- **THEN** `list_org_members` 同时返回两者，`kind` 分别为 `human` 与 `agent`
- **AND** 两者共享同一套角色枚举（owner/admin/member/viewer）

### Requirement: 频道 ACL（基础权限）
系统 SHALL 用 `channel_members` 表实现频道 ACL，`can_access_channel` 为单一判定入口；非成员不可见频道内容，组织管理员（owner/admin）可见本组织全部频道。

#### Scenario: 非成员不可见频道
- **WHEN** 成员 `u2` 不在频道 `private` 的 ACL 中
- **THEN** `can_access_channel(private, u2)` 返回 `False`
- **AND** `list_channels_for_user(u2)` 不包含 `private`

#### Scenario: 组织管理员可见全部频道
- **WHEN** 组织管理员 `u1` 查询频道列表
- **THEN** 返回本组织所有频道（含不在其 ACL 中的私有频道）

### Requirement: 组织 API 路由
系统 SHALL 通过 HTTP 暴露组织/部门/频道/成员/ACL 的创建与查询接口，写操作按角色鉴权。

#### Scenario: 通过 API 创建组织与频道
- **WHEN** 调用 `POST /api/orgs`、`POST /api/orgs/{org_id}/channels`
- **THEN** 返回新建实体，数据落库 `org.db`
- **AND** 非组织管理员对成员/频道写操作返回 403

### Requirement: 频道即群聊（Agent 群聊）
系统 SHALL 把 `Channel` 与 `GroupStore`/`RoomMessageStore` 桥接，使频道内 Human 与多 Agent 可协同对话、消息可分发、可回放。

#### Scenario: 频道成员同步到群聊花名册
- **WHEN** 频道建立并加入成员后桥接到 `GroupStore`
- **THEN** 频道成员以 `invite` 事件同步到对应 thread 的 `GroupState`
- **AND** 可复用 `fold_state` 重建群聊状态

#### Scenario: 消息持久化
- **WHEN** 频道内成员发送消息
- **THEN** 消息追加到 `RoomMessageStore`（per-channel 落盘）
- **AND** 重启后可通过 `history()` 恢复，消息不丢

## MODIFIED Requirements

（无 —— 本变更不修改既有能力，只新增企业空间层。）

## REMOVED Requirements

（无 —— 本变更不删除既有能力。）