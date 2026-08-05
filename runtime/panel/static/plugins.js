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

// --- 状态 ---
let plugins = [];
let pluginMeta = {};
let activeGroup = null;

const PROVIDER_KIND_ORDER = [
    "runtime_capability",
    "builtin_foundation",
    "builtin_optional",
    "mcp_capability",
    "capability_pack",
    "ai_draft",
    "external_plugin",
    "mixed",
    "builtin_other",
];
const RUNTIME_CAPABILITY_IDS = new Set(["attachment", "memory"]);
const FOUNDATION_CAPABILITY_IDS = new Set(["filesystem", "code", "shell", "git"]);
const OPTIONAL_CAPABILITY_IDS = new Set(["document", "web"]);

// --- API 请求 ---
async function loadPlugins() {
    try {
        const result = await api("/plugins");
        plugins = result.data || [];
        pluginMeta = result.meta || {};
        renderSidebar();
        renderPluginList();
        renderSummary();
        renderGuidance();
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

// --- 渲染 ---
function renderSummary() {
    const loadablePlugins = plugins.filter((p) => !isReadOnlyPlugin(p));
    const total = loadablePlugins.length;
    const enabled = loadablePlugins.filter((p) => p.enabled).length;
    const runtimeCount = plugins.filter((p) => providerKind(p) === "runtime_capability").length;
    const mcpCount = plugins.filter((p) => providerKind(p) === "mcp_capability").length;
    const packCount = plugins.filter((p) => providerKind(p) === "capability_pack").length;
    const draftCount = plugins.filter((p) => providerKind(p) === "ai_draft").length;
    const hasDepIssue = plugins.some((p) => {
        const deps = p.dependencies || {};
        return Object.values(deps).some((ok) => !ok);
    });
    let text = t('plugins_js.capability_summary', {enabled, total, runtime: runtimeCount, mcp: mcpCount});
    if (packCount) text += t('plugins_js.capability_pack_count', {count: packCount});
    if (draftCount) text += t('plugins_js.ai_draft_count', {count: draftCount});
    if (hasDepIssue) text += t('plugins_js.dep_missing');
    $("plugin-summary").textContent = text;
}

function renderGuidance() {
    const target = $("ai-plugin-draft-root");
    if (!target) return;
    const root = pluginMeta.capability_pack_root || pluginMeta.ai_plugin_draft_root || "";
    target.textContent = root ? t('plugins_js.capability_pack_root', {path: root}) : "";
}

function renderSidebar() {
    const container = $("plugin-group-list");
    const allActive = !activeGroup ? "active" : "";
    let html = `<button class="plugin-group-item ${allActive}" data-group="">${t('plugins_js.all_capabilities')}</button>`;
    for (const kind of orderedProviderKinds(plugins)) {
        const items = plugins.filter((plugin) => providerKind(plugin) === kind);
        html += `<div class="plugin-group-heading">${escapeHtml(providerKindLabel(kind))}</div>`;
        for (const plugin of items) {
            const active = activeGroup === plugin.id ? "active" : "";
            const depOk = isDepsOk(plugin);
            const badge = plugin.capability_pack
                ? `<span class="sample-badge-mini">${t('plugins_js.capability_pack_short')}</span>`
                : plugin.ai_draft
                ? `<span class="sample-badge-mini">${t('plugins_js.ai_draft_short')}</span>`
                : depOk ? "" : `<span class="dep-badge">⚠</span>`;
            html += `<button class="plugin-group-item ${active}" data-group="${plugin.id}">${escapeHtml(plugin.name)}${badge}</button>`;
        }
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
        container.innerHTML = `<div class="empty-state">${t('plugins_js.no_capability_data')}</div>`;
        return;
    }
    container.innerHTML = activeGroup
        ? filtered.map(renderPluginCard).join("")
        : orderedProviderKinds(filtered).map((kind) => renderPluginSection(
            kind,
            filtered.filter((plugin) => providerKind(plugin) === kind),
        )).join("");
    // 绑定开关
    container.querySelectorAll(".plugin-toggle").forEach((btn) => {
        btn.addEventListener("change", (e) => {
            const pluginId = e.target.dataset.plugin;
            togglePlugin(pluginId, e.target.checked);
        });
    });
}

function renderPluginSection(kind, items) {
    return `
        <section class="plugin-provider-section">
            <div class="plugin-provider-heading">${escapeHtml(providerKindLabel(kind))}</div>
            ${items.map(renderPluginCard).join("")}
        </section>
    `;
}

function renderPluginCard(plugin) {
    const deps = plugin.dependencies || {};
    const depEntries = Object.entries(deps);
    const requirementEntries = dependencyRequirementEntries(plugin.dependency_requirements || {});
    const depsHtml = depEntries.length
        ? `<div class="plugin-deps">
            <span class="deps-label">${t('plugins_js.deps_label')}</span>
            ${depEntries.map(([name, ok]) => `<span class="dep-item ${ok ? "ok" : "missing"}">${escapeHtml(name)} ${ok ? "✓" : "✗"}</span>`).join("")}
           </div>`
        : "";
    const requirementsHtml = requirementEntries.length
        ? `<div class="plugin-meta">
            <span class="deps-label">${t('plugins_js.requirements_label')}</span>
            ${requirementEntries.map((item) => `<span class="dep-item requirement">${escapeHtml(item)}</span>`).join("")}
           </div>`
        : "";
    const toolsHtml = (plugin.tools || [])
        .map((t) => `<span class="tool-chip">${escapeHtml(t.name || t.id)}</span>`)
        .join("");
    const statusBadge = `<span class="plugin-status-badge">${escapeHtml(providerKindLabel(providerKind(plugin), plugin))}</span>`;
    const lockHtml = plugin.toggle_locked
        ? `<div class="plugin-meta"><span class="dep-item requirement">${escapeHtml(toggleLockLabel(plugin))}</span></div>`
        : "";
    const toggleHtml = isReadOnlyPlugin(plugin)
        ? ""
        : `<label class="toggle-switch">
            <input type="checkbox" class="plugin-toggle" data-plugin="${plugin.id}" ${plugin.enabled ? "checked" : ""}>
            <span class="toggle-slider"></span>
        </label>`;
    return `
        <div class="plugin-card ${plugin.enabled || isReadOnlyPlugin(plugin) ? "" : "disabled"}">
            <div class="plugin-card-header">
                <div class="plugin-card-info">
                    <h3 class="plugin-card-title">${escapeHtml(plugin.name)}${statusBadge}</h3>
                    <p>${escapeHtml(plugin.description)}</p>
                </div>
                ${toggleHtml}
            </div>
            ${depsHtml}
            ${requirementsHtml}
            ${lockHtml}
            <div class="plugin-tools">${toolsHtml}</div>
        </div>
    `;
}

function isDepsOk(plugin) {
    const deps = plugin.dependencies || {};
    return Object.values(deps).every((ok) => ok);
}

function isReadOnlyPlugin(plugin) {
    return Boolean(
        plugin.toggle_locked
        || providerKind(plugin) === "runtime_capability"
        || plugin.capability_pack
        || plugin.ai_draft
        || plugin.contract_sample
        || plugin.source_type === "mcp"
    );
}

function providerKind(plugin) {
    if (plugin.provider_kind) return plugin.provider_kind;
    if (plugin.ai_draft) return "ai_draft";
    if (plugin.capability_pack) return "capability_pack";
    if (plugin.source_type === "mcp") return "mcp_capability";
    if (plugin.source_type === "capability_pack") return "capability_pack";
    if (plugin.source_type && plugin.source_type !== "builtin") return "external_plugin";
    if (RUNTIME_CAPABILITY_IDS.has(plugin.id)) return "runtime_capability";
    if (FOUNDATION_CAPABILITY_IDS.has(plugin.id)) return "builtin_foundation";
    if (OPTIONAL_CAPABILITY_IDS.has(plugin.id)) return "builtin_optional";
    return "builtin_other";
}

function providerKindLabel(kind, plugin = null) {
    return plugin?.provider_label || t(`plugins.kind.${kind || "builtin_other"}`);
}

function orderedProviderKinds(items) {
    const present = new Set(items.map(providerKind));
    return [
        ...PROVIDER_KIND_ORDER.filter((kind) => present.has(kind)),
        ...Array.from(present).filter((kind) => !PROVIDER_KIND_ORDER.includes(kind)).sort(),
    ];
}

function toggleLockLabel(plugin) {
    const kind = providerKind(plugin);
    if (kind === "runtime_capability") return t("plugins_js.managed_by_runtime");
    if (kind === "mcp_capability") return t("plugins_js.managed_by_mcp");
    if (kind === "capability_pack") return t("plugins_js.managed_by_capability_pack");
    if (kind === "ai_draft") return t("plugins_js.draft_read_only");
    return t("plugins_js.read_only");
}

function dependencyRequirementEntries(requirements) {
    const entries = [];
    if (requirements.node) entries.push(`Node ${requirements.node}`);
    if (requirements.python) entries.push(`Python ${requirements.python}`);
    for (const binary of requirements.binaries || []) {
        entries.push(binary);
    }
    for (const pkg of requirements.packages || []) {
        entries.push(pkg);
    }
    for (const service of requirements.optional_system_services || []) {
        entries.push(service);
    }
    return entries;
}

// --- 事件 ---
$("back-btn").addEventListener("click", () => {
    window.location.href = "/";
});
$("mcp-services-btn").addEventListener("click", () => {
    window.location.href = "/mcp-services-page";
});
$("refresh-plugins-btn").addEventListener("click", () => loadPlugins());

// --- 初始化 ---
loadPlugins();
