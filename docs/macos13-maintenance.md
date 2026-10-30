# macOS 13 兼容补丁维护边界

本轮审查基于已同步的上游 `ade5b21e8dca43d9ac7a8302bf582d461ac9d283`
和兼容分支 `b03100cb46ebdc25d7ad6624b508d938bedaacd0`；这不是持续跟踪上游最新提交的声明。

目标是减少兼容判断对上游业务代码的侵入，而不是通过移动文件或删除测试制造更小的 diff。
不要为了合并方便移除仍在使用的回退路径，也不要在同步上游的同一批提交里升级 Qt、重做缓存或调整发布策略。

## 保留和集中处理的位置

| 边界 | 维护位置 | 同步上游时的检查 |
| --- | --- | --- |
| ScreenCaptureKit 系统能力与旧系统回退 | `snow-crates/crates/snow-macos/src/{capabilities,capture,content}.rs` | 新 selector 必须先核对能力条件；保留 macOS 13 单帧截图回退 |
| Qt 屏幕与 AppKit 显示器映射 | `snow_shot/src/platform/macos/qtscreencompat_p.h` | 业务几何算法只调用适配入口；不要重新内嵌 NSScreen 枚举或新 Qt 原生屏幕 API |
| Qt 版本与数据流格式 | `scripts/qt-toolchain.json`、`snow_shot/include/snow_shot/persistence/qtdatastreamversion.h` | Qt 升级与持久化数据格式变更必须分别验证，不能用修改数字来绕过编译错误 |
| C++ 标准库回退 | `cmake/SnowMacOSCxx20Compat.cmake`、`cmake/macos-cxx20-compat/`、`snow_image/include/snow/image/detail/stop_wait.h` | 保留原生能力探测和隔离后的 backport；等待取消不能只依赖一次 notify |
| 导出控制器构造契约 | `imageeditingexportcontroller.{h,cpp}` | 同时检查公开 Pin 类型、外层转发、Impl 参数和成员初始化；不能只让构造调用通过编译 |
| 更新渠道隔离 | `snow_shot/include/snow_shot/app/distribution.h` 及现有调用点 | 保留兼容版禁用上游自动更新的行为 |
| 构建缓存与发布产物 | 兼容版独立工作流和 `scripts/macos13-compile-cache.sh` | 发布只选择两个架构的安装包 artifact，不将缓存归档作为 Release 附件 |

屏幕适配本次只迁移现有实现，不改变按逻辑矩形匹配显示器的策略。
镜像显示器、热插拔、缩放与多屏布局仍需要真实 Mac 回归，头文件语法检查不能证明这些运行行为。

## 每次同步的步骤

1. 固定并记录上游提交，先同步源码；将编译器、Qt、缓存与打包调整分成独立提交。
2. 逐项审查上表的交界处。Git 没有文本冲突不代表接口仍一致。
3. 运行相关的快速检查：

   ```sh
   python3 scripts/test-macos13-source-compat.py -v
   python3 scripts/test-macos13-compile-cache.py -v
   python3 scripts/test-macos-build-support.py QtMacOSDeploymentPolicy \
     MacOSBuildScripts.test_ci_cached_build_reuses_only_compiler_outputs_and_packages_once -v
   ```

4. 日常 push 只运行轻量 Preflight，不额外跑完整 smoke。发版时核对源版本、
   远端 HEAD 和未占用的 `macos13-v<version>-r<revision>`，再创建 tag。
   完整双架构编译、打包和 Release 都由该 tag 工作流完成；分支手动 dispatch 被拒绝。
   重试已有 tag 只验证该 tag 的固定提交，不允许覆盖 tag 指向。
5. 工作流仅在 ARM64 和 Intel 构建、打包和校验都成功后发布。确认运行记录中的 SHA
   与 tag 一致，核对 Full ARM64、Mini ARM64、Full Intel 三个包及校验文件。
   CI 不能替代 Ventura 真机启动、截图、多屏选区和贴图验证；发布说明须明确该限制。

不要把重跑旧 tag 当作验证新代码。不要以 Preflight 绿色替代整包构建成功。
不运行无筛选的全量 CTest 或 Rust workspace 测试。

## 快速检查的证明范围

`test-macos13-source-compat.py` 从实际源码读取 Impl 字段、构造函数和参数转发，
用最小 Qt 类型替身编译并验证回调初始化；同时反向验证旧的两参数构造函数和删除 Pin 参数会被拒绝。
这不是完整控制器或 Qt 行为测试。

取消等待检查直接编译生产 helper，在具备原生 overload 的标准库上保持原生路径，
并强制执行旧库 fallback 和通知先于等待的交错。原生 Preflight 用实际 backport 再运行同一检查。

macOS runner 额外使用真实 SDK、macOS 13 部署目标和 Qt 类型替身检查屏幕适配头文件。
Linux 明确跳过该 SDK 检查。它验证语法与 API 可用性，不验证 Qt ABI、实际显示器匹配或系统运行兼容性。

Preflight 覆盖兼容分支、`fix/macos13-*` 修复分支以及目标为兼容分支的 PR，
不发布 Release，也不构建完整应用。全量原生构建仅使用兼容版 tag 工作流，不重复维护第二套打包流程。
