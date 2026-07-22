import { Command } from "@tauri-apps/plugin-shell";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./styles.css";

const statusText = document.querySelector("#status-text");
const runtimeLog = document.querySelector("#runtime-log");
const runtimeFrame = document.querySelector("#runtime-frame");
const bootPanel = document.querySelector("#boot-panel");

let stdoutBuffer = "";
let runtimeChild = null;
let runtimeReady = false;
let runtimeExited = false;
let runtimePid = null;
let runtimeUrl = "";
let runtimeErrorText = "";
let closingWindow = false;
const runtimeHost = "127.0.0.1";
const stdoutDecoder = new TextDecoder("utf-8", { fatal: false });
const stderrDecoder = new TextDecoder("utf-8", { fatal: false });
const runtimeToken = createRuntimeToken();
const runtimeProfile = normalizeRuntimeProfile(
  import.meta.env.VITE_YUNTAOCODE_RUNTIME_PROFILE,
);

setStatus("准备启动 Python sidecar...");
installWindowLifecycleHandlers();
startRuntime().catch((error) => {
  setStatus(`启动失败：${error.message}`);
  appendLog(String(error.stack || error.message || error));
});

async function startRuntime() {
  const runtimePort = await invoke("find_free_port", { host: runtimeHost });
  runtimeUrl = `http://${runtimeHost}:${runtimePort}`;
  const args = [
    "--host",
    runtimeHost,
    "--port",
    String(runtimePort),
    "--token",
    runtimeToken,
    "--profile",
    runtimeProfile,
  ];
  const command = Command.sidecar("binaries/local-runtime", args, {
    encoding: "raw",
    env: {
      PYTHONIOENCODING: "utf-8:replace",
      PYTHONUTF8: "1",
    },
  });

  command.stdout.on("data", (chunk) => {
    handleStdout(decodeOutputChunk(chunk, stdoutDecoder));
  });

  command.stderr.on("data", (chunk) => {
    const text = decodeOutputChunk(chunk, stderrDecoder);
    runtimeErrorText = `${runtimeErrorText}${text}`.slice(-4000);
    appendLog(text);
  });

  command.on("close", (event) => {
    runtimeExited = true;
    runtimePid = null;
    if (!runtimeReady) {
      const detail = runtimeErrorText.trim();
      const suffix = detail ? `：${firstLine(detail)}` : "";
      setStatus(`本地运行时已退出，退出码：${event.code ?? "unknown"}${suffix}`);
    }
  });

  command.on("error", (error) => {
    setStatus(`sidecar 错误：${error}`);
    appendLog(String(error));
  });

  runtimeChild = await command.spawn();
  runtimePid = runtimeChild.pid;
  window.__localRuntimeChild = runtimeChild;
  setStatus(`Python sidecar 已启动，等待本地运行时响应：${runtimeUrl}`);
  void waitForRuntimeReady(runtimeUrl, { timeoutMs: 45000 }).catch((error) => {
    if (!runtimeReady && !runtimeExited) {
      const detail = firstLine(runtimeErrorText.trim());
      const suffix = detail ? `：${detail}` : "";
      setStatus(`本地运行时未就绪：${error.message}${suffix}`);
    }
  });
}

function handleStdout(chunk) {
  stdoutBuffer += chunk;
  const lines = stdoutBuffer.split(/\r?\n/);
  stdoutBuffer = lines.pop() || "";
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    appendLog(trimmed);
    tryHandleReady(trimmed);
  }
}

function tryHandleReady(line) {
  let payload;
  try {
    payload = JSON.parse(line);
  } catch {
    return;
  }
  if (payload.event !== "ready" || !payload.url) return;

  markRuntimeReady(payload.url);
}

function markRuntimeReady(url) {
  if (runtimeReady) return;
  runtimeReady = true;
  runtimeUrl = url;
  setStatus(`本地运行时已就绪：${url}`);
  runtimeFrame.src = url;
  runtimeFrame.classList.add("ready");
  bootPanel.classList.add("hidden");
}

function appendLog(text) {
  runtimeLog.textContent = `${runtimeLog.textContent}${text}\n`.slice(-6000);
}

function setStatus(text) {
  statusText.textContent = text;
}

function decodeOutputChunk(chunk, decoder) {
  if (chunk instanceof Uint8Array) {
    return decoder.decode(chunk, { stream: true });
  }
  if (Array.isArray(chunk)) {
    return decoder.decode(new Uint8Array(chunk), { stream: true });
  }
  return String(chunk ?? "");
}

function firstLine(text) {
  return String(text || "").split(/\r?\n/).find((line) => line.trim())?.trim() || "";
}

function normalizeRuntimeProfile(value) {
  const normalized = String(value || "full").trim().toLowerCase();
  return normalized === "lite" ? "lite" : "full";
}

function createRuntimeToken() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  if (!window.crypto?.getRandomValues) {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
  const bytes = new Uint8Array(24);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function installWindowLifecycleHandlers() {
  const appWindow = getCurrentWindow();
  appWindow.onCloseRequested((event) => {
    if (closingWindow) return;
    event.preventDefault();
    closingWindow = true;
    void closeWindowAfterRuntimeStop(appWindow);
  }).catch((error) => {
    appendLog(`窗口关闭清理监听失败：${error?.message || error}`);
  });
}

async function closeWindowAfterRuntimeStop(appWindow) {
  setStatus("正在关闭本地运行时...");
  await stopRuntime({ timeoutMs: 5000 });
  await requestAppExit(appWindow);
}

async function requestAppExit(appWindow) {
  try {
    await withTimeout(invoke("exit_app"), 1000);
    return;
  } catch (error) {
    appendLog(`应用退出命令失败，改用窗口关闭：${error?.message || error}`);
  }
  await requestWindowClose(appWindow);
}

async function requestWindowClose(appWindow) {
  try {
    await withTimeout(appWindow.close(), 1000);
  } catch (error) {
    appendLog(`窗口关闭失败，改用强制销毁：${error?.message || error}`);
    try {
      await withTimeout(appWindow.destroy(), 1000);
    } catch (destroyError) {
      appendLog(`窗口销毁失败：${destroyError?.message || destroyError}`);
    }
  }
}

async function stopRuntime({ timeoutMs = 1500 } = {}) {
  const child = runtimeChild;
  runtimeChild = null;
  if (runtimeExited) return;

  const gracefulBudget = Math.min(timeoutMs, 3500);
  const shutdownSent = await requestRuntimeShutdown(Math.min(gracefulBudget, 1200));
  if (shutdownSent && await waitForRuntimeExit(Math.max(800, gracefulBudget - 1200))) {
    return;
  }

  if (!runtimeExited && runtimePid) {
    try {
      await withTimeout(invoke("kill_process_tree", { pid: runtimePid }), Math.min(timeoutMs, 2500));
      runtimeExited = true;
      runtimePid = null;
      return;
    } catch (error) {
      appendLog(`sidecar 进程树清理失败：${error?.message || error}`);
    }
  }

  if (child && typeof child.kill === "function") {
    try {
      await withTimeout(child.kill(), Math.min(timeoutMs, 800));
      await waitForRuntimeExit(Math.min(timeoutMs, 500));
    } catch (error) {
      appendLog(`sidecar 结束失败：${error?.message || error}`);
    }
  }
}

async function requestRuntimeShutdown(timeoutMs) {
  if (!runtimeUrl) return false;
  try {
    await withTimeout(fetch(`${runtimeUrl}/_runtime/shutdown`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "X-YuntaoCode-Token": runtimeToken,
      },
    }), timeoutMs);
    return true;
  } catch (error) {
    appendLog(`运行时关闭请求失败：${error?.message || error}`);
    return false;
  }
}

async function waitForRuntimeReady(url, { timeoutMs = 45000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  while (Date.now() < deadline) {
    if (runtimeReady) return true;
    if (runtimeExited) {
      throw new Error("sidecar exited before runtime became ready");
    }
    try {
      const response = await fetch(`${url}/health`, { cache: "no-store" });
      if (response.ok) {
        markRuntimeReady(url);
        return true;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error?.message || String(error);
    }
    await delay(250);
  }
  throw new Error(lastError || "ready timeout");
}

function waitForRuntimeExit(timeoutMs) {
  if (runtimeExited) return Promise.resolve(true);
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      if (runtimeExited) {
        window.clearInterval(timer);
        resolve(true);
        return;
      }
      if (Date.now() - startedAt >= timeoutMs) {
        window.clearInterval(timer);
        resolve(false);
      }
    }, 50);
  });
}

function withTimeout(promise, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("operation timed out")), timeoutMs);
    Promise.resolve(promise).then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function delay(milliseconds) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

window.addEventListener("beforeunload", () => {
  if (runtimeChild && typeof runtimeChild.kill === "function") {
    void stopRuntime({ timeoutMs: 500 });
  }
});
