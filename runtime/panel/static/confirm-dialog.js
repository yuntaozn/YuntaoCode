/**
 * 应用内确认对话框。
 *
 * 页面通过 showConfirmDialog() 获取用户选择，避免桌面 WebView 调用原生
 * confirm() 时创建独立系统窗口。业务代码仍负责决定何时需要确认。
 */

(function installConfirmDialog() {
    let pendingResolve = null;
    let lastFocusedElement = null;

    function translated(key, fallback) {
        if (typeof t !== "function") return fallback;
        const value = t(key);
        return value && value !== key ? value : fallback;
    }

    function ensureDialog() {
        const existing = document.getElementById("app-confirm-dialog");
        if (existing) return existing;

        const dialog = document.createElement("dialog");
        dialog.id = "app-confirm-dialog";
        dialog.className = "app-confirm-dialog";
        dialog.setAttribute("aria-labelledby", "app-confirm-title");
        dialog.setAttribute("aria-describedby", "app-confirm-message");
        dialog.innerHTML = `
            <div class="app-confirm-panel">
                <h2 id="app-confirm-title"></h2>
                <p id="app-confirm-message"></p>
                <div class="dialog-actions">
                    <button class="secondary-button" id="app-confirm-cancel" type="button"></button>
                    <button class="primary-button" id="app-confirm-submit" type="button"></button>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);

        dialog.querySelector("#app-confirm-cancel").addEventListener("click", () => settle(false));
        dialog.querySelector("#app-confirm-submit").addEventListener("click", () => settle(true));
        dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            settle(false);
        });
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) settle(false);
        });
        return dialog;
    }

    function settle(confirmed) {
        const dialog = document.getElementById("app-confirm-dialog");
        const resolve = pendingResolve;
        pendingResolve = null;
        if (dialog?.open) dialog.close();
        if (lastFocusedElement instanceof HTMLElement && lastFocusedElement.isConnected) {
            lastFocusedElement.focus();
        }
        lastFocusedElement = null;
        if (resolve) resolve(confirmed);
    }

    window.showConfirmDialog = function showConfirmDialog(message, options = {}) {
        const dialog = ensureDialog();
        if (pendingResolve) settle(false);

        const title = options.title || translated("common.confirm_title", "请确认");
        const cancelLabel = options.cancelLabel || translated("common.cancel", "取消");
        const confirmLabel = options.confirmLabel || translated("common.confirm", "确认");
        const submitButton = dialog.querySelector("#app-confirm-submit");

        dialog.querySelector("#app-confirm-title").textContent = title;
        dialog.querySelector("#app-confirm-message").textContent = String(message || "");
        dialog.querySelector("#app-confirm-cancel").textContent = cancelLabel;
        submitButton.textContent = confirmLabel;
        submitButton.className = options.danger ? "danger-button" : "primary-button";
        lastFocusedElement = document.activeElement;

        return new Promise((resolve) => {
            pendingResolve = resolve;
            dialog.showModal();
            submitButton.focus();
        });
    };
})();
