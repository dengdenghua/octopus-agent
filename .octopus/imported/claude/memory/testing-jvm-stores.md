---
name: testing-jvm-stores
description: octopus-mobile 单测窍门：MMKV 未初始化时 KVUtils 退回内存 map，故 store-backed 逻辑可纯 JVM 测，无需 Robolectric
metadata: 
  node_type: memory
  type: reference
  originSessionId: aa494889-9cf1-4899-a403-3e5977c80b7a
---

octopus-mobile 写单测时：`KVUtils`(MMKV 键值存储)在 `!::mmkv.isInitialized` 时**自动退回内存 `ConcurrentHashMap`**(getString/putString 都有该分支)。单测里 MMKV 从不初始化(`TestClawApplication.initializeApp()` 是空的;MMKV 在 JVM 会触发 `android.os.Process.is64Bit` 的 NoSuchMethodError)。

**结论:** 凡是只经由 `KVUtils.getString/putString`(非 SECURE_KEYS)持久化的对象——`ActionCache`、`RoutineStore`、`RoutineParameterizer` 等——都能当**纯 JVM 测**(`org.junit.Test` + `org.junit.Assert.*`),不用 `@Config(application=TestClawApplication::class)`/Robolectric。

**2026-06 起 boolean 路径也有兜底:** `getBoolean/putBoolean` 也加了 `boolFallback` 内存 map(commit d39b650),`remove()` 会同时清 string/bool fallback。所以 boolean-backed 的安全层——`PermissionModeManager`(满血模式开关)、`ChannelAccessControl`(渠道 ACL,`isChannelAclEnabled` 默认 true)——现在也能纯 JVM 测了。范式见 `app/src/test/.../safety/PermissionModeManagerTest.kt`、`channel/ChannelAccessControlTest.kt`。注意 `getFloat/getDouble/getInt/getLong` 仍**无**兜底,测到它们会 lateinit 崩。

注意:`stringFallback` 是 `object` 静态字段,跨用例/跨测试类在同一 JVM fork 里**不会自动清**——`@Before` 里手动清:`RoutineStore.all().forEach{remove(it.id)}` + `ActionCache.all().forEach{remove(it.routineId)}`。

SECURE_KEYS(API Key/Bot Token/AppSecret/Auth Token)走 EncryptedSharedPreferences,那条路单测不可用——别测那些。

范式见 `app/src/test/.../RoutineParameterizerTest.kt`(本会话新增)。自动化引擎仍大量缺测:FastReplay/RoutineRunner(依赖无障碍/线程,较难)、PopupDetector/VisionMarkersTool(依赖 svc)。相关:[[build-and-release]]
