/**
 * 插件管理独立页面逻辑
 */
const $ = (id) => document.getElementById(id);

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message) {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: { "Content-Type": "application/json; charset=utf-8", "Accept-Language": getLocale() },
        ...options,
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || data.message || response.statusText);
    }
    return response.json();
}

// --- State ---
let plugins = [];
let activeGroup = null;

// --- API ---
async function loadPlugins() {
    try {
        const result = await api("/plugins");
        plugins = result.data || [];
        renderSidebar();
        renderPluginList();
        renderSummary();
    } catch (err) {
        showToast(t('plugins_js.load_failed', {error: err.message}));
    }
}

async function togglePlugin(pluginId, enabled) {
    try {
        await api("/plugins", {
            method: "POST",
            body: JSON.stringify({ plugin_id: pluginId, enabled }),
        });
        // 更新本地状态
        const plugin = plugins.find((p) => p.id === pluginId);
        if (plugin) plugin.enabled = enabled;
        renderPluginList();
        renderSummary();
        showToast(t('plugins_js.toggled', {id: pluginId, state: enabled ? t('plugins_js.enabled') : t('plugins_js.disabled')}));
    } catch (err) {
        showToast(t('plugins_js.op_failed', {error: err.message}));
    }
}

// --- Render ---
function renderSummary() {
    const total = plugins.length;
    const enabled = plugins.filter((p) => p.enabled).length;
    const hasDepIssue = plugins.some((p) => {
        const deps = p.dependencies || {};
        return Object.values(deps).some((ok) => !ok);
    });
    let text = t('plugins_js.enabled_count', {enabled, total});
    if (hasDepIssue) text += t('plugins_js.dep_missing');
    $("plugin-summary").textContent = text;
}

function renderSidebar() {
    const container = $("plugin-group-list");
    const allActive = !activeGroup ? "active" : "";
    let html = `<button class="plugin-group-item ${allActive}" data-group="">${t('plugins_js.all_plugins')}</button>`;
    for (const plugin of plugins) {
        const active = activeGroup === plugin.id ? "active" : "";
        const depOk = isDepsOk(plugin);
        const badge = depOk ? "" : `<span class="dep-badge">⚠</span>`;
        html += `<button class="plugin-group-item ${active}" data-group="${plugin.id}">${escapeHtml(plugin.name)}${badge}</button>`;
    }
    container.innerHTML = html;
    // 绑定点击
    container.querySelectorAll(".plugin-group-item").forEach((btn) => {
        btn.addEventListener("click", () => {
            activeGroup = btn.dataset.group || null;
            renderSidebar();
            renderPluginList();
        });
    });
}

function renderPluginList() {
    const container = $("plugin-list-full");
    const filtered = activeGroup ? plugins.filter((p) => p.id === activeGroup) : plugins;
    if (!filtered.length) {
        container.innerHTML = `<div class="empty-state">${t('plugins_js.no_data')}</div>`;
        return;
    }
    container.innerHTML = filtered.map(renderPluginCard).join("");
    // 绑定开关
    container.querySelectorAll(".plugin-toggle").forEach((btn) => {
        btn.addEventListener("change", (e) => {
            const pluginId = e.target.dataset.plugin;
            togglePlugin(pluginId, e.target.checked);
        });
    });
}

function renderPluginCard(plugin) {
    const deps = plugin.dependencies || {};
    const depEntries = Object.entries(deps);
    const depsHtml = depEntries.length
        ? `<div class="plugin-deps">
            <span class="deps-label">${t('plugins_js.deps_label')}</span>
            ${depEntries.map(([name, ok]) => `<span class="dep-item ${ok ? "ok" : "missing"}">${escapeHtml(name)} ${ok ? "✓" : "✗"}</span>`).join("")}
           </div>`
        : "";
    const toolsHtml = (plugin.tools || [])
        .map((t) => `<span class="tool-chip">${escapeHtml(t.name || t.id)}</span>`)
        .join("");
    return `
        <div class="plugin-card ${plugin.enabled ? "" : "disabled"}">
            <div class="plugin-card-header">
                <div class="plugin-card-info">
                    <h3>${escapeHtml(plugin.name)}</h3>
                    <p>${escapeHtml(plugin.description)}</p>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox" class="plugin-toggle" data-plugin="${plugin.id}" ${plugin.enabled ? "checked" : ""}>
                    <span class="toggle-slider"></span>
                </label>
            </div>
            ${depsHtml}
            <div class="plugin-tools">${toolsHtml}</div>
        </div>
    `;
}

function isDepsOk(plugin) {
    const deps = plugin.dependencies || {};
    return Object.values(deps).every((ok) => ok);
}

// --- Events ---
$("back-btn").addEventListener("click", () => {
    window.location.href = "/";
});
$("refresh-plugins-btn").addEventListener("click", () => loadPlugins());

// --- Init ---
loadPlugins();
