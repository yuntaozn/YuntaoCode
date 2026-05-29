# Tauri 桌面壳

这个目录是 YuntaoCode（云涛智能终端）的 Tauri v2 桌面壳。它的职责很窄：

1. 启动随安装包携带的 Python sidecar。
2. 读取 sidecar 输出的 `{"event":"ready","url":"..."}`。
3. 在桌面窗口中用 iframe 加载 Python runtime 提供的本地面板。
4. 窗口关闭时尝试结束 sidecar 进程。

Python runtime 仍然负责本地工具、模型调用、对话存储、项目目录和设置。

## 开发环境

Windows 首次开发需要安装：

- Node.js 18+。
- Rust MSVC 工具链和 Cargo。
- Microsoft C++ Build Tools。
- WebView2 Runtime。
- Python 3.11+，并安装 `requirements.txt`。
- PyInstaller，用于把 Python runtime 打成 sidecar。

Rust/Cargo 当前机器如果还没装，先按 Tauri 官方 prerequisites 安装。

## 安装依赖

```powershell
cd D:\code\aiagent\二十二冶\local-intelligent-terminal
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

cd desktop-shell
npm install
```

## 构建 Python sidecar

Tauri v2 的 `externalBin` 需要目标平台后缀。Windows x64 对应：

```text
local-runtime-x86_64-pc-windows-msvc.exe
```

运行：

```powershell
cd D:\code\aiagent\二十二冶\local-intelligent-terminal\desktop-shell
npm run sidecar:windows
```

脚本会把产物复制到：

```text
desktop-shell/src-tauri/binaries/local-runtime-x86_64-pc-windows-msvc.exe
```

## 开发运行

```powershell
cd D:\code\aiagent\二十二冶\local-intelligent-terminal\desktop-shell
npm run dev
```

窗口打开后会先显示启动页，然后拉起 Python sidecar。sidecar 选择随机可用端口，所以不会和你浏览器调试时的 `8765` 冲突。

## 构建 Windows 安装包

```powershell
cd D:\code\aiagent\二十二冶\local-intelligent-terminal\desktop-shell
npm run build:windows
```

输出目录通常在：

```text
desktop-shell/src-tauri/target/release/bundle/nsis/
```

首版优先走 NSIS `.exe` 安装器。MSI 可以后续再补 WiX 配置。

## 当前边界

- sidecar 使用 `--host 127.0.0.1 --port 0` 启动。
- 目录白名单仍由 Python runtime 的 `PathGuard` 管理。
- 用户身份验证仍通过本地面板登录 `aipython`。
- Tauri 父页面只负责进程生命周期；实际业务 UI 仍来自 Python runtime 的面板。
