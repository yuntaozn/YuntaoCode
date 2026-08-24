# Tauri 桌面壳

这个目录是 YuntaoCode（云涛智能终端）的 Tauri v2 桌面壳。它的职责很窄：

1. 启动随安装包携带的 Python sidecar。
2. 为 sidecar 分配本机端口，并通过 `/health` 轮询确认 runtime 就绪。
3. 在桌面窗口中用 iframe 加载 Python runtime 提供的本地面板。
4. 窗口关闭时先请求 runtime 关闭，再兜底清理 sidecar 进程树并退出应用。

Python runtime 仍然负责本地工具、模型调用、对话存储、项目目录和设置。

桌面应用图标位于：

```text
desktop-shell/src-tauri/icons/icon.ico
```

## 开发环境

Windows 首次开发需要安装：

- Node.js 18+。
- Rust MSVC 工具链和 Cargo。
- Microsoft C++ Build Tools。
- WebView2 Runtime。
- Python 3.10+。sidecar 构建脚本会创建独立的 `.venv-sidecar-build`
  环境，避免把日常 Python 环境中的大型可选库误打进安装包。

Rust/Cargo 当前机器如果还没装，先按 Tauri 官方 prerequisites 安装。

## 安装依赖

```powershell
cd YuntaoCode
cd desktop-shell
npm ci
```

## 构建 Python sidecar

Tauri v2 的 `externalBin` 需要目标平台后缀。Windows x64 对应：

```text
local-runtime-x86_64-pc-windows-msvc.exe
```

运行：

```powershell
cd YuntaoCode\desktop-shell
npm run sidecar:windows
```

默认构建 `full` sidecar，会包含文档、网页预览、桌面观察等完整产品能力。
如果只想验证核心 Runtime 或制作轻量包，可以构建 `lite` sidecar：

```powershell
cd YuntaoCode\desktop-shell
npm run sidecar:windows:lite
```

`lite` 只包含附件、文件、代码、Shell、Git 和记忆等核心工具组。它适合体积
验证和最小运行时冒烟，不适合作为完整能力发行包。

脚本会把产物复制到：

```text
desktop-shell/src-tauri/binaries/local-runtime-x86_64-pc-windows-msvc.exe
```

临时 PyInstaller 文件在成功后会自动删除。需要清理失败构建留下的
sidecar、spec、dist 和安装包中间产物时，运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\clean_desktop_build.ps1
```

追加 `-Full` 会同时删除隔离构建环境和 Cargo `target` 缓存，下次构建会
重新下载或编译依赖。

## 开发运行

```powershell
cd YuntaoCode\desktop-shell
npm run dev
```

窗口打开后会先显示启动页，然后拉起 Python sidecar。sidecar 选择随机可用端口，所以不会和你浏览器调试时的 `8765` 冲突。

## 构建 Windows 安装包

```powershell
cd YuntaoCode\desktop-shell
npm run build:windows
```

Windows sidecar 和安装包构建命令默认都生成无控制台程序，避免安装后出现独立黑框。
NSIS 安装器当前固定为简体中文，以避免 Windows/NSIS 记住上次语言选择后
导致默认语言漂移。英文安装器可以后续用单独构建配置补充。
如果需要诊断 sidecar 启动日志，可以构建明确标记的控制台版本：

```powershell
powershell -ExecutionPolicy Bypass -File ..\scripts\build_desktop_windows.ps1 -ConsoleSidecar
# 或只构建控制台 sidecar
npm run sidecar:windows:console
```

如需构建轻量安装包：

```powershell
cd YuntaoCode\desktop-shell
npm run build:windows:lite
```

输出目录通常在：

```text
desktop-shell/src-tauri/target/release/bundle/nsis/
```

Windows 首次生成 NSIS 安装包时，Tauri 还会从其官方 GitHub Release
下载并校验 NSIS 工具链，缓存到 `%LOCALAPPDATA%\tauri\NSIS`。网络无法
访问 GitHub Release 时，verbose 构建日志会停在 `Verifying NSIS package`；
这不表示 Rust 主程序或 Python sidecar 构建失败。后续可在可访问 GitHub
的网络或 CI 中完成首次缓存/打包。

首版优先走 NSIS `.exe` 安装器。MSI 可以后续再补 WiX 配置。

## 当前边界

- sidecar 使用 `--host 127.0.0.1 --port 0` 启动。
- 目录白名单仍由 Python runtime 的 `PathGuard` 管理。
- 用户身份验证仍通过本地面板登录 `aipython`。
- Tauri 父页面只负责进程生命周期；实际业务 UI 仍来自 Python runtime 的面板。
