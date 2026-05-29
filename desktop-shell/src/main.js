import { Command } from "@tauri-apps/plugin-shell";
import "./styles.css";

const statusText = document.querySelector("#status-text");
const runtimeLog = document.querySelector("#runtime-log");
const runtimeFrame = document.querySelector("#runtime-frame");
const bootPanel = document.querySelector("#boot-panel");

let stdoutBuffer = "";
let runtimeChild = null;
let runtimeReady = false;

setStatus("准备启动 Python sidecar...");
startRuntime().catch((error) => {
  setStatus(`启动失败：${error.message}`);
  appendLog(String(error.stack || error.message || error));
});

async function startRuntime() {
  const args = ["--host", "127.0.0.1", "--port", "0"];
  const command = Command.sidecar("binaries/local-runtime", args);

  command.stdout.on("data", (chunk) => {
    handleStdout(String(chunk));
  });

  command.stderr.on("data", (chunk) => {
    appendLog(String(chunk));
  });

  command.on("close", (event) => {
    if (!runtimeReady) {
      setStatus(`本地运行时已退出，退出码：${event.code ?? "unknown"}`);
    }
  });

  command.on("error", (error) => {
    setStatus(`sidecar 错误：${error}`);
    appendLog(String(error));
  });

  runtimeChild = await command.spawn();
  window.__localRuntimeChild = runtimeChild;
  setStatus("Python sidecar 已启动，等待 ready 信号...");
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

  runtimeReady = true;
  setStatus(`本地运行时已就绪：${payload.url}`);
  runtimeFrame.src = payload.url;
  runtimeFrame.classList.add("ready");
  bootPanel.classList.add("hidden");
}

function appendLog(text) {
  runtimeLog.textContent = `${runtimeLog.textContent}${text}\n`.slice(-6000);
}

function setStatus(text) {
  statusText.textContent = text;
}

window.addEventListener("beforeunload", () => {
  if (runtimeChild && typeof runtimeChild.kill === "function") {
    runtimeChild.kill();
  }
});
