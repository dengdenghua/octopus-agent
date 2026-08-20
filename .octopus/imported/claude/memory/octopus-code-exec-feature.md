---
name: octopus-code-exec-feature
description: 给 octopus 加「设备上编程」工具的决策与已验证的执行路径(QuickJS + Shizuku + /data/local/tmp)
metadata: 
  node_type: memory
  type: project
  originSessionId: 339a0daf-4314-4e54-9372-090ca7948fdb
---

目标:给 Agent 加「在设备上执行生成代码」的能力(用户称"编程")。2026-06-30 设计 + spike 验证。

关键决策:
- 解释器选 **QuickJS**(~1MB 单文件静态二进制,可编译期砍 os/std 模块做纯计算沙箱)。静态 CPython(~15MB)/MicroPython 已否。
- 定位为 **Shizuku-only 高级功能**(没授权 Shizuku 即不可用),用户已接受。
- 执行模型:首启从服务器拉二进制 → /sdcard → Shizuku `cp` 进 `/data/local/tmp/octopus/` → 以 shell UID exec。**APK 0 增量**。

为什么能绕过 W^X:targetSdk=36 的 untrusted_app 不能 exec 私有目录,但 [[tentacle-mother-control]] 用的 ShizukuShellService 跑在 **shell 域(uid 2000)**,shell 域可 exec `/data/local/tmp`(`shell_data_file`),与 targetSdk 无关。`/data/local/tmp` 已在 ShizukuShellService 的 ALLOWED_PATH_PREFIXES。

已验证(2026-06-30,emulator-5554,Android 16 / sdk36 / SELinux Enforcing / userdebug):拷 toybox 成新文件放进 /data/local/tmp 并 exec 副本,exit 0。架构成立。靠 AOSP 核心 sepolicy `allow shell shell_data_file:file execute`(非 userdebug 专属)→ 会迁移到 user build 真机。待真机 + Shizuku.newProcess 路径最终确认。

最大难点不是体积/W^X,是安全:解释器一进去**命令白名单即失效**(os.system 能干任何 shell 能干的、shell UID = ADB 级权限)。管控点须上移到工具级:CodeExecTool 登记为 ToolRiskPolicy 最高危(加漂移守护测试,见 [[tool-system-internals]])+ guardrail 人工确认 + 审计日志;脚本只落沙箱目录。

qjs 构建已验证(2026-07-01):NDK r28c(28.2.13676358)+ cmake 3.31.6 交叉编译 quickjs-ng,target `qjs_exe`,flags `-DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 -DCMAKE_BUILD_TYPE=MinSizeRel`。产物 4MB(未 strip,strip 后~1.5MB)aarch64 PIE,**NEEDED 仅 libc/libm/libdl(全 bionic,自洽)**。push 进 sdk36 模拟器 exec 跑通:console.log/JSON/Date/Math 全 OK。构建脚本逻辑见会话(cmake+Ninja)。注:NDK 走 sdkmanager 下载会被截断,得 curl `-C -` 单调续传 dl.google.com/.../android-ndk-r28c-darwin.zip(952495160 字节)。quickjs-ng 是纯 C,无 libc++ 依赖。

沙箱 runner 已验证(2026-07-01):自建 qjs-runner.c 只 `JS_NewContext`(标准 intrinsics)+ 手注 console.log,**不调 js_init_module_std/os、不链 libqjs-libc.a**。编译产物 781K(strip),`llvm-nm` 证实**零 js_os_/js_std_/js_init_module 符号**(编译期砍死,非运行时禁)。模拟器实测:纯计算/Math/JSON/Date/regex 全 OK;os/std/require/scriptArgs 全 undefined;`os.exec()` 抛 ReferenceError 无法逃逸。内存限 64MB+栈 1MB。源码/构建脚本在会话 scratchpad(qjs-runner.c + build-runner.sh,clang 直链 libqjs.a)。

设计已定(用户选 A=沿用统一管线):run_code 登记 HIGH→自动走 ToolRegistry.executeTool 的高危来源闸门(ApprovalFlow,仅不可信来源弹窗)+审计,零新增闸门。4 新件:ShizukuShellService.runQuickJs(argv 直 exec 不走 sh -c/白名单,脚本传文件零注入)+ QuickJsRuntime(分发)+ RunCodeTool + 自建 runner。4 登记点:HIGH_RISK_TOOLS / NON_IDEMPOTENT_TOOLS / Guardrail.DANGEROUS_TOOLS / ToolRegistry.register。漂移守护测试从 HIGH 集自动派生,无需改测试。staging:脚本/二进制 App 写自己 getExternalFilesDir(/sdcard/Android/data/<pkg>,shell 有 ext_data_rw 组可读)→ Shizuku cp 进 /data/local/tmp/octopus → chmod。

阶段:0 spike ✅ / 工具链 ✅ / 沙箱 runner ✅ → 正在写 Kotlin 集成 → 待验:真机 Shizuku.newProcess 全链路。

**2026-07-05 落库 + 安全加固(feat/script-sandbox-upgrade 已 cherry-pick 进本地 main,未 push):**
代码能力已从 spike 扩成正式功能:JS 沙箱 ScriptSandbox(Rhino,ClassShutter{false} 结构性禁碰 Java)、**Python 沙箱 PythonSandbox(Chaquopy CPython 3.11 + run_python)**、ShellExecTool(Shizuku shell)、per-session 工作空间、EditFileTool。多 agent 审计(见会话)判 fix-before-merge,两个 high 已修:
- **Python 沙箱越权**:原把完整 __builtins__+os 塞用户命名空间,`open('/data/data/.../mmkv/mmkv.default')` 直接读 octo 令牌/LLM key,绕过 isSafePath。改用 **PEP 578 审计钩子 sys.addaudithook**(裁剪 builtins 挡不住子类遍历逃逸,审计钩子在 C 层拦真正的 open/subprocess/exec)。守卫在 `app/src/main/python/octopus_sandbox.py` 的 `_guard`:进程/exec/fork/dlopen + 软硬链一律拒;open/变更/目录列举落 /data、/proc、/sys 拒(仅放行 sys.path 运行时读);rename dst 也查;**策略全内联字面量 + 装钩子前把 abspath/fspath/白名单快照进默认参数**,回调不读 sys.modules/模块属性 → 置空模块全局、sys.modules['os']=Fake、monkeypatch abspath 都架空不了(前后两轮红队证伪+堵洞,详见会话)。残余(inherent):os.stat/readlink 无审计事件的元数据泄露、直连 _posixsubprocess/ctypes.CDLL(None)、改 _guard.__code__ 深度 introspection —— 超出「挡 LLM 生成码现实逃逸」目标。
- **shell_exec find -delete**:`find … -delete` 穿白名单+注入检测删文件。ShellExecTool 加 containsDangerousFindPredicate(find 分词含 -delete/-exec/-execdir/-ok/-fprintf/-fls 即拒),单测 ShellExecFindGuardTest。
- **回归验证**:Python 守卫用宿主 python3 跑 `scripts/verify_octopus_sandbox.py`(20 条对抗用例:逃逸+篡改+正常,全绿)—— Chaquopy 需 Android 运行时,JVM CI 覆盖不了,故用宿主 CPython 等价验证(审计事件名 3.11/宿主一致)。JS 侧 isSafePath/callTool 闸门审计判 SAFE。CI 四件套全绿。
本地 main 领先 origin 11 提交、**未 push**(含上述 + billing + 个人网页/产物面板等整条分支)。[[security-audit-2026-06]] 是另一轮审计。
