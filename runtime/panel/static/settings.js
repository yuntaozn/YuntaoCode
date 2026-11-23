const $ = (id) => document.getElementById(id);

let settings = null;
let backups = [];
let backupMeta = {};
let memories = [];  // 从 /memories API 加载
let activeSettingsPage = localStorage.getItem("lit_settings_page") || "models";
const deletedProviderIds = new Set();
const deletedModelIds = new Set();
const standardEndpoint = /\/(chat\/completions|responses)$/;

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML.replaceAll('"', "&quot;");
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

function setDynamicText(id, text) {
    const element = $(id);
    if (!element) return;
    element.removeAttribute("data-i18n");
    element.textContent = text;
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options,
        headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Language": getLocale(),
            ...(options.headers || {}),
        },
    });
    const raw = await response.text();
    let payload = {};
    try {
        payload = raw ? JSON.parse(raw) : {};
    } catch {
        payload = { success: false, error: raw || response.statusText };
    }
    if (!response.ok || !payload.success) {
        throw new Error(payload.error || payload.message || response.statusText);
    }
    return payload.data;
}

async function loadAll() {
    const [settingsData, backupData, memoryData] = await Promise.all([
        api("/settings"),
        api("/backups").catch(() => ({ items: [] })),
        api("/memories").catch(() => ({ items: [] })),
    ]);
    settings = settingsData;
    backups = backupData.items || [];
    backupMeta = backupData || {};
    memories = memoryData.items || [];
    applyI18n();
    renderSettings();
    renderBackups();
}

function providerEntries() {
    return Object.values(settings?.providers || {});
}

function modelEntries() {
    return Array.isArray(settings?.models) ? settings.models : [];
}

function memoryEntries() {
    return Array.isArray(memories) ? memories : [];
}

function memoryScopeLabel(memory) {
    return memory?.scope === "workspace"
        ? t("settings_js.memory_scope_workspace")
        : t("settings_js.memory_scope_global");
}

function renderSettings() {
    settings.providers = settings.providers || {};
    settings.models = settings.models || [];
    settings.memories = settings.memories || { enabled: true, max_active: 30, auto_extract: true };
    const backupSettings = settings?.backups || {};
    const memorySettings = settings?.memories || {};

    renderDefaultModelOptions();
    renderProviders();
    renderModels();
    renderMemories();

    $("access-scope-input").value = settings?.access_scope || "project_only";
    $("confirmation-policy-input").value = settings?.confirmation_policy || "auto";
    $("backup-enabled-input").checked = backupSettings.enabled !== false;
    $("backup-keep-input").value = backupSettings.keep_rounds || 50;
    $("memory-enabled-input").checked = memorySettings.enabled !== false;
    $("memory-max-active-input").value = Number(memorySettings.max_active ?? 30);
    $("memory-auto-extract-input").checked = memorySettings.auto_extract !== false;
    setDynamicText("settings-path", settings?.settings_path || "");
    if (activeSettingsPage === "providers") $("provider-card").open = true;
    showSettingsPage(activeSettingsPage, false);
    renderSummary();
}

function renderDefaultModelOptions(selected = settings.default_model) {
    const models = modelEntries();
    $("default-model-input").innerHTML = models.map((model) => `
        <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)} · ${escapeHtml(providerDisplayName(model.provider))}</option>
    `).join("");
    if (models.some((model) => model.id === selected)) {
        $("default-model-input").value = selected;
    } else if (models[0]) {
        $("default-model-input").value = models[0].id;
    }
}

function renderProviders() {
    const providers = providerEntries();
    $("provider-list").innerHTML = providers.length ? providers.map((provider) => `
        <details class="settings-item provider-item" data-provider-id="${escapeHtml(provider.id)}">
            <summary>${escapeHtml(provider.name || provider.id)} · <span data-linked-count>${t('settings_js.linked_models', {count: linkedModelCount(provider.id)})}</span></summary>
            <div class="settings-fields">
                <div class="settings-form-row">
                    <label>${t('settings_js.provider_name')}</label>
                    <input data-provider-field="name" value="${escapeHtml(provider.name || "")}">
                </div>
                <div class="settings-inline">
                    <div class="settings-form-row">
                        <label>Base URL</label>
                        <input data-provider-field="base_url" value="${escapeHtml(provider.base_url || "")}" placeholder="http://127.0.0.1:11434/v1">
                    </div>
                    <div class="settings-form-row">
                        <label>Chat Path</label>
                        <input data-provider-field="chat_path" value="${escapeHtml(provider.chat_path || "/chat/completions")}">
                    </div>
                </div>
                <div class="settings-inline">
                    <div class="settings-form-row">
                        <label>API Key</label>
                        <input data-provider-field="api_key" type="password" placeholder="${t('settings_js.leave_empty')}">
                        <span class="hint-line">${provider.has_api_key ? t('settings_js.key_configured', {hint: escapeHtml(provider.api_key_hint)}) : t('settings_js.no_key_hint')}</span>
                    </div>
                    <label class="checkbox-line compact">
                        <input data-provider-field="api_key_required" type="checkbox" ${provider.api_key_required !== false ? "checked" : ""}>
                        <span>${t('settings_js.require_key')}</span>
                    </label>
                </div>
                <div class="settings-form-row">
                    <label>${t('settings_js.provider_params')}</label>
                    <textarea data-provider-field="request_options" placeholder='{"temperature":0.2}'>${escapeHtml(JSON.stringify(provider.request_options || {}, null, 2))}</textarea>
                    <span class="hint-line">${t('settings_js.advanced_request_params_hint')}</span>
                </div>
                <div><button class="secondary-button danger-button" type="button" data-delete-provider="${escapeHtml(provider.id)}">${t('settings_js.remove_provider')}</button></div>
            </div>
        </details>
    `).join("") : `<div class="hint-line">${t('settings_js.no_providers')}</div>`;
}

function renderModels() {
    const models = modelEntries();
    $("model-list").innerHTML = models.length ? models.map((model) => `
        <div class="settings-item model-item" data-model-id="${escapeHtml(model.id)}">
            <div class="settings-item-head">
                <div class="settings-item-title">
                    <strong>${escapeHtml(model.name || model.id)}</strong>
                    <span>${escapeHtml(model.api_model || model.id)} · ${escapeHtml(providerDisplayName(model.provider))}</span>
                </div>
                <div class="dialog-actions">
                    <button class="secondary-button" type="button" data-edit-model="${escapeHtml(model.id)}">${t('settings_js.edit_model')}</button>
                    <button class="secondary-button danger-button" type="button" data-delete-model="${escapeHtml(model.id)}">${t('settings_js.remove_model')}</button>
                </div>
            </div>
        </div>
    `).join("") : `<div class="hint-line">${t('settings_js.no_models')}</div>`;
}

function renderMemories() {
    const allMemories = memoryEntries();
    const filter = $("memory-filter-input")?.value || "";
    const filtered = filter ? allMemories.filter((m) => m.source === filter) : allMemories;
    const enabledCount = allMemories.filter((item) => item.enabled !== false).length;

    setDynamicText("memory-storage-hint", allMemories.length
        ? t('settings_js.memories_count', {enabled: enabledCount, total: allMemories.length})
        : t('settings_js.no_memories'));

    const sourceLabels = { manual: t('settings_js.source_manual'), auto: t('settings_js.source_auto'), conversation: t('settings_js.source_conversation') };

    $("memory-list").innerHTML = filtered.length ? filtered.map((memory) => {
        const sourceLabel = sourceLabels[memory.source] || memory.source || t('settings_js.source_manual');
        const createdAt = memory.created_at ? new Date(memory.created_at).toLocaleDateString() : "";
        const usageInfo = memory.usage_count ? t('settings_js.memory_usage', {count: memory.usage_count}) : "";
        const metaInfo = [memoryScopeLabel(memory), sourceLabel, createdAt, usageInfo].filter(Boolean).join(" · ");

        return `
        <div class="settings-item memory-item" data-memory-id="${escapeHtml(memory.id)}">
            <div class="settings-item-head">
                <div class="settings-item-title">
                    <strong>${escapeHtml(memory.text || t('settings_js.memory_unnamed'))}</strong>
                    <span>${escapeHtml((memory.tags || []).join("、") || t('settings_js.memory_no_tags'))}</span>
                </div>
                <div style="display:flex;gap:6px;align-items:center;">
                    <span style="font-size:11px;color:var(--muted);">${escapeHtml(metaInfo)}</span>
                    <button class="secondary-button" type="button" data-save-memory="${escapeHtml(memory.id)}" title="${t('settings_js.memory_save_btn')}">${t('settings_js.memory_save_btn')}</button>
                    <button class="secondary-button danger-button" type="button" data-delete-memory="${escapeHtml(memory.id)}">${t('settings_js.memory_delete_btn')}</button>
                </div>
            </div>
            <label class="checkbox-line compact">
                <input data-memory-field="enabled" type="checkbox" ${memory.enabled !== false ? "checked" : ""}>
                <span>${t('settings_js.memory_enabled')}</span>
            </label>
            <div class="settings-form-row">
                <label>${t('settings_js.memory_text_label')}</label>
                <textarea data-memory-field="text" maxlength="500" placeholder="${t('settings_js.memory_text_placeholder')}">${escapeHtml(memory.text || "")}</textarea>
            </div>
            <div class="settings-form-row">
                <label>${t('settings_js.memory_tags_label')}</label>
                <input data-memory-field="tags" value="${escapeHtml((memory.tags || []).join(", "))}" placeholder="${t('settings_js.memory_tags_placeholder')}">
            </div>
        </div>
    `}).join("") : `<div class="hint-line">${filter ? t('settings_js.no_memory_filter') : t('settings_js.no_memory_all')}</div>`;
}

function renderProviderOptions(selected) {
    const providers = providerEntries();
    return providers.map((provider) => `
        <option value="${escapeHtml(provider.id)}" ${provider.id === selected ? "selected" : ""}>${escapeHtml(provider.name || provider.id)}</option>
    `).join("");
}

function providerDisplayName(providerId) {
    const provider = providerEntries().find((item) => item.id === providerId);
    return provider?.name || providerId || t('settings_js.no_provider_selected');
}

function linkedModelCount(providerId) {
    return modelEntries().filter((model) => model.provider === providerId).length;
}

function renderSummary() {
    const accessText = $("access-scope-input").value === "full_local" ? t('settings_js.summary_full') : t('settings_js.summary_project');
    const confirmMap = { conservative: t('settings_js.confirm_conservative'), auto: t('settings_js.confirm_auto'), aggressive: t('settings_js.confirm_aggressive') };
    const confirmation = confirmMap[$("confirmation-policy-input").value] || t('settings_js.confirm_auto');
    const memoryCount = memoryEntries().filter((item) => item.enabled !== false).length;
    setDynamicText("settings-summary", t('settings_js.summary_text', {
        access: accessText,
        confirmation,
        providers: providerEntries().length,
        models: modelEntries().length,
        memories: memoryCount,
    }));
}

function renderBackups() {
    const items = backups || [];
    const total = Number(backupMeta.total_count || items.length || 0);
    setDynamicText("backup-storage-hint", items.length
        ? t('backup.recent_n_files', {n: items.length, total: total, files: Number(backupMeta.total_file_count || 0)})
        : t('backup.none'));
    $("backup-list").innerHTML = items.length ? items.slice(0, 50).map((item, index) => `
        <div class="backup-item">
            <div class="backup-item-main">
                <strong>${escapeHtml(backupRecordTitle(item, index))}</strong>
                <span>${escapeHtml(item.tool_id || "")} · ${t('backup.files', {count: Number(item.file_count || 0)})}</span>
                <em>${escapeHtml(formatBackupTime(item.created_at))}${item.restored_at ? t('backup.restored') : ""}</em>
                ${renderBackupFiles(item)}
            </div>
            <button type="button" class="secondary-button backup-restore-btn" data-restore-backup="${escapeHtml(item.id || "")}">${t('backup.restore')}</button>
        </div>
    `).join("") : `<div class="hint-line">${t('backup.hint')}</div>`;
}

function backupRecordTitle(item, index) {
    const files = Array.isArray(item?.files) ? item.files : [];
    const names = files.map((file) => backupFileLabel(file)).filter(Boolean);
    const count = Number(item?.file_count || names.length || 0);
    if (names.length) {
        const shown = names.slice(0, 2).join("、");
        return count > 2 ? t('backup.n_files_etc', {shown, count}) : shown;
    }
    return index === 0 ? t('backup.recent_latest') : t('backup.recent_n', {n: index + 1});
}

function backupFileLabel(file) {
    if (file?.name) return String(file.name);
    const path = String(file?.path || "");
    if (!path) return file?.existed === false ? t('settings_js.new_file') : t('settings_js.unknown_file');
    return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function renderBackupFiles(item, limit = 20) {
    const files = Array.isArray(item?.files) ? item.files : [];
    if (!files.length) return "";
    const shown = files.slice(0, limit);
    const count = Number(item?.file_count || files.length);
    const more = Math.max(0, count - shown.length);
    return `
        <div class="backup-file-list">
            ${shown.map((file) => `
                <div class="backup-file-row" title="${escapeHtml(file.path || "")}">
                    <span class="backup-file-name">${escapeHtml(backupFileLabel(file))}</span>
                    <span class="backup-file-path">${escapeHtml(file.path || "")}${file.existed === false ? ` · ${t('settings_js.new_file')}` : ""}</span>
                </div>
            `).join("")}
            ${more ? `<div class="backup-file-more">${t('backup.more_files', {count: more})}</div>` : ""}
        </div>
    `;
}

function formatBackupTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
}

function readJson(text) {
    const value = String(text || "").trim();
    if (!value) return {};
    let parsed;
    try {
        parsed = JSON.parse(value);
    } catch (error) {
        throw new Error(t("settings_js.json_error", {error: error.message}));
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(t("settings_js.json_object"));
    }
    return parsed;
}

function collectProviders() {
    const providers = Object.create(null);
    document.querySelectorAll(".provider-item").forEach((item) => {
        const id = item.dataset.providerId;
        providers[id] = {
            name: item.querySelector('[data-provider-field="name"]').value.trim() || id,
            base_url: item.querySelector('[data-provider-field="base_url"]').value.trim(),
            chat_path: item.querySelector('[data-provider-field="chat_path"]').value.trim() || "/chat/completions",
            api_key_required: item.querySelector('[data-provider-field="api_key_required"]').checked,
            request_options: readJson(item.querySelector('[data-provider-field="request_options"]').value),
            enabled: true,
        };
        const path = providers[id].chat_path;
        if (path !== settings.providers[id].chat_path) {
            const endpoint = ("/" + path.split("?")[0]).replace(/\/+$/, "").match(standardEndpoint);
            if (endpoint) providers[id].wire_api = endpoint[1] === "responses" ? "responses" : "chat_completions";
        }
        const apiKey = item.querySelector('[data-provider-field="api_key"]').value.trim();
        if (apiKey) providers[id].api_key = apiKey;
    });
    return providers;
}

async function saveSettings(modelChanges) {
    const payload = modelChanges || {
        providers: collectProviders(),
        models: modelEntries(),
        default_model: $("default-model-input").value,
        access_scope: $("access-scope-input").value,
        confirmation_policy: $("confirmation-policy-input").value,
        backups: {
            enabled: $("backup-enabled-input").checked,
            keep_rounds: Number($("backup-keep-input").value || 50),
        },
        memories: {
            enabled: $("memory-enabled-input").checked,
            max_active: Number($("memory-max-active-input").value || 30),
            auto_extract: $("memory-auto-extract-input").checked,
        },
    };
    payload.deleted_provider_ids = Array.from(deletedProviderIds);
    payload.deleted_model_ids = Array.from(deletedModelIds);
    settings = await api("/settings", {
        method: "POST",
        body: JSON.stringify(payload),
    });
    deletedProviderIds.clear();
    deletedModelIds.clear();
    localStorage.setItem("lit_model", settings.default_model || $("default-model-input").value);
    if (modelChanges) {
        renderDefaultModelOptions();
        renderModels();
        renderProviders();
        renderSummary();
    } else {
        localStorage.setItem("lit_confirmation_policy", settings.confirmation_policy);
        renderSettings();
    }
    showToast(t('toast.settings_saved'));
}

async function refreshBackups() {
    const data = await api("/backups");
    backups = data.items || [];
    backupMeta = data || {};
    renderBackups();
}

async function restoreBackup(backupId) {
    if (!backupId) return;
    if (!await showConfirmDialog(t('backup.confirm_restore'))) return;
    const result = await api(`/backups/${encodeURIComponent(backupId)}/restore`, {
        method: "POST",
        body: JSON.stringify({}),
    });
    await refreshBackups();
    showToast(t('backup.restored_n', {count: Number(result.restored_file_count || 0)}));
}

async function restoreLatestBackup() {
    const latest = backups?.[0];
    if (!latest?.id) {
        showToast(t('backup.no_restore'));
        return;
    }
    await restoreBackup(latest.id);
}

async function clearBackups() {
    if (!await showConfirmDialog(t('backup.confirm_clear'), {danger: true})) return;
    const data = await api("/backups", { method: "DELETE" });
    backups = data.items || [];
    backupMeta = data || {};
    renderBackups();
    showToast(t('backup.cleared'));
}

function showSettingsPage(page, persist = true) {
    const pages = Array.from(document.querySelectorAll("[data-settings-page]"));
    const available = new Set(pages.map((item) => item.dataset.settingsPage));
    activeSettingsPage = available.has(page) ? page : "models";
    pages.forEach((item) => {
        item.hidden = item.dataset.settingsPage !== activeSettingsPage;
    });
    document.querySelectorAll("[data-settings-page-button]").forEach((button) => {
        button.classList.toggle("active", button.dataset.settingsPageButton === activeSettingsPage);
    });
    if (persist) {
        localStorage.setItem("lit_settings_page", activeSettingsPage);
    }
}

function defaultThinkingModeForProvider(providerId) {
    if (providerId === "volcengine") return "volcengine";
    if (providerId === "qwen") return "qwen";
    return "";
}

function modelIdFromApiModel(provider, apiModel) {
    const base = String(apiModel || "").trim();
    const providerId = String(provider || "").trim();
    const models = modelEntries();
    if (!models.some((model) => String(model.id || "") === base)) {
        return base;
    }
    const providerScoped = `${providerId}:${base}`;
    if (!models.some((model) => String(model.id || "") === providerScoped)) {
        return providerScoped;
    }
    let index = 2;
    while (models.some((model) => String(model.id || "") === `${providerScoped}:${index}`)) {
        index += 1;
    }
    return `${providerScoped}:${index}`;
}

// 新连接接受服务根地址、带前缀的 Base URL 或完整的标准端点。
function connectionFromAddress(address) {
    let url;
    try {
        url = new URL(address.trim());
    } catch {
        throw new Error(t("settings_js.invalid_address"));
    }
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.hash) {
        throw new Error(t("settings_js.invalid_address"));
    }
    const path = url.pathname.replace(/\/+$/, "");
    const endpoint = path.match(standardEndpoint);
    const basePath = endpoint ? path.slice(0, endpoint.index) : path || "/v1";
    return {
        name: url.host + basePath,
        base_url: url.origin + basePath,
        chat_path: (endpoint ? endpoint[0] : "/chat/completions") + url.search,
        wire_api: endpoint?.[1] === "responses" ? "responses" : "chat_completions",
    };
}

function syncConnectionFields() {
    const fields = $("model-form").elements;
    const providerId = fields.provider.value;
    const row = Array.from(document.querySelectorAll(".provider-item")).find(item => item.dataset.providerId === providerId);
    fields.address.readOnly = Boolean(row);
    $("shared-address-hint").hidden = !row;
    const base = row?.querySelector('[data-provider-field="base_url"]').value.trim() || "";
    const path = row?.querySelector('[data-provider-field="chat_path"]').value.trim() || "/chat/completions";
    fields.address.value = base ? base.replace(/\/+$/, "") + "/" + path.replace(/^\/+/, "") : "";
    fields.api_key.value = "";
    const provider = settings.providers[providerId];
    $("model-key-hint").textContent = provider?.has_api_key
        ? t("settings_js.shared_key", { hint: provider.api_key_hint })
        : t("settings_js.optional_key");
}

function openModelDialog(model = null, connectionOnly = false) {
    const form = $("model-form");
    const fields = form.elements;
    form.reset();
    form.dataset.modelId = model?.id || "";
    form.dataset.newConnectionId = "connection-" + Array.from(crypto.getRandomValues(new Uint32Array(2)), n => n.toString(16)).join("-");
    form.classList.toggle("connection-only", connectionOnly);
    fields.api_model.required = !connectionOnly;
    fields.provider.innerHTML = renderProviderOptions(model?.provider);
    fields.provider.prepend(new Option(t("settings_js.new_connection"), ""));
    fields.provider.value = model?.provider || "";
    syncConnectionFields();
    const modelTitle = model ? "settings_js.edit_model" : "settings_page.add_model";
    $("model-dialog-title").textContent = t(connectionOnly ? "settings_page.add_provider" : modelTitle);
    $("advanced-model-settings").open = false;
    $("model-form-error").textContent = "";
    if (model) {
        for (const [name, value] of Object.entries(model)) {
            const input = fields.namedItem(name);
            if (!input || name === "provider") continue;
            if (input.type === "checkbox") input.checked = value;
            else if (name === "request_options") input.value = JSON.stringify(value, null, 2);
            else {
                if (input.type === "select-one" && !Array.from(input.options).some(option => option.value === value)) {
                    input.add(new Option(value, value));
                }
                input.value = value;
            }
        }
    }
    // 默认模型可在列表中切换。编辑当前默认模型时保留此选择。
    fields.make_default.checked = Boolean(model && model.id === $("default-model-input").value);
    fields.make_default.disabled = fields.make_default.checked;
    $("model-dialog").showModal();
}

async function submitModelForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = form.elements;
    const submit = $("submit-model");
    if (submit.disabled) return;
    submit.disabled = true;
    form.inert = true;
    $("model-form-error").textContent = "";
    try {
        const providers = collectProviders();
        let providerId = fields.provider.value;
        const key = fields.api_key.value.trim();
        if (!providerId) {
            const connection = connectionFromAddress(fields.address.value);
            providerId = form.dataset.newConnectionId;
            providers[providerId] = { ...connection, api_key_required: Boolean(key), enabled: true };
        }
        if (key) providers[providerId].api_key = key;

        const models = modelEntries().slice();
        let defaultModel = $("default-model-input").value;
        if (!form.classList.contains("connection-only")) {
            const editingId = form.dataset.modelId;
            const apiModel = fields.api_model.value.trim();
            if (!apiModel) throw new Error(t("settings_js.model_required"));
            if (models.some(model => model.id !== editingId && model.provider === providerId && model.api_model === apiModel)) {
                throw new Error(t("settings_js.model_exists"));
            }
            const index = models.findIndex(model => model.id === editingId);
            const model = {
                ...models[index],
                id: editingId || modelIdFromApiModel(providerId, apiModel),
                api_model: apiModel,
                provider: providerId,
            };
            for (const input of $("advanced-model-settings").querySelectorAll("[name]")) {
                if (input.type === "checkbox") model[input.name] = input.checked;
                else if (input.name === "request_options") model.request_options = readJson(input.value);
                else if (input.type === "number") model[input.name] = Number(input.value || input.defaultValue);
                else model[input.name] = input.value.trim();
            }
            model.name ||= model.id === apiModel ? apiModel : `${apiModel} · ${providers[providerId].name}`;
            if (index < 0) models.push(model);
            else models[index] = model;
            if (fields.make_default.checked || !defaultModel) defaultModel = model.id;
        }
        await saveSettings({ providers, models, default_model: defaultModel });
        $("model-dialog").close();
    } catch (error) {
        $("model-form-error").textContent = error.message;
    } finally {
        form.inert = false;
        submit.disabled = false;
    }
}

async function addMemory() {
    const text = window.prompt(t('settings_js.memory_prompt'));
    if (!text || !text.trim()) return;
    try {
        const result = await api("/memories", {
            method: "POST",
            body: JSON.stringify({
                text: text.trim(),
                tags: [],
                source: "manual",
            }),
        });
        memories = [result, ...memories];
        activeSettingsPage = "memories";
        renderSettings();
        showToast(t('settings_js.memory_added'));
    } catch (error) {
        showToast(t('settings_js.add_failed', {error: error.message}));
    }
}

async function saveMemory(memoryId) {
    const item = document.querySelector(`[data-memory-id="${memoryId}"]`);
    if (!item) return;
    const text = item.querySelector('[data-memory-field="text"]').value.trim().slice(0, 500);
    const tags = item.querySelector('[data-memory-field="tags"]').value
        .split(/[,，]/)
        .map((t) => t.trim().slice(0, 24))
        .filter(Boolean)
        .slice(0, 6);
    const enabled = item.querySelector('[data-memory-field="enabled"]').checked;
    try {
        const result = await api(`/memories/${encodeURIComponent(memoryId)}`, {
            method: "PUT",
            body: JSON.stringify({ text, tags, enabled }),
        });
        // 更新本地记忆数组。
        const idx = memories.findIndex((m) => m.id === memoryId);
        if (idx >= 0) memories[idx] = result;
        showToast(t('settings_js.memory_saved'));
    } catch (error) {
        showToast(t('settings_js.save_failed', {error: error.message}));
    }
}

async function deleteMemoryFn(memoryId) {
    if (!await showConfirmDialog(t('settings_js.confirm_delete_memory'), {danger: true})) return;
    try {
        await api(`/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
        memories = memories.filter((m) => m.id !== memoryId);
        renderSettings();
        showToast(t('settings_js.memory_deleted'));
    } catch (error) {
        showToast(t('settings_js.delete_failed', {error: error.message}));
    }
}

function bindEvents() {
    $("back-btn").addEventListener("click", () => window.location.href = "/");
    $("cancel-btn").addEventListener("click", () => window.location.href = "/");
    $("refresh-settings-btn").addEventListener("click", () => loadAll().then(() => showToast(t('settings_page.refreshed'))).catch((error) => showToast(error.message)));
    $("save-settings-btn").addEventListener("click", () => saveSettings().catch((error) => showToast(error.message)));
    $("add-provider-btn").addEventListener("click", () => openModelDialog(null, true));
    $("add-model-btn").addEventListener("click", () => openModelDialog());
    $("model-form").addEventListener("submit", submitModelForm);
    $("cancel-model-dialog").addEventListener("click", () => $("model-dialog").close());
    $("close-model-dialog").addEventListener("click", () => $("model-dialog").close());
    $("model-dialog").addEventListener("close", () => { $("model-form").elements.api_key.value = ""; });
    $("model-dialog").addEventListener("cancel", (event) => {
        if ($("submit-model").disabled) event.preventDefault();
    });
    $("model-form").elements.provider.addEventListener("change", (event) => {
        syncConnectionFields();
        $("model-form").elements.thinking_mode.value = defaultThinkingModeForProvider(event.target.value);
    });
    $("add-memory-btn").addEventListener("click", addMemory);
    $("refresh-backups-btn").addEventListener("click", () => refreshBackups().catch((error) => showToast(error.message)));
    $("restore-latest-backup-btn").addEventListener("click", () => restoreLatestBackup().catch((error) => showToast(error.message)));
    $("clear-backups-btn").addEventListener("click", () => clearBackups().catch((error) => showToast(error.message)));
    $("access-scope-input").addEventListener("change", renderSummary);
    $("confirmation-policy-input").addEventListener("change", renderSummary);
    $("memory-filter-input").addEventListener("change", renderMemories);
    document.querySelectorAll("[data-settings-page-button]").forEach((button) => {
        button.addEventListener("click", () => {
            showSettingsPage(button.dataset.settingsPageButton);
        });
    });
    document.addEventListener("click", async (event) => {
        const restoreButton = event.target.closest("[data-restore-backup]");
        if (restoreButton) {
            restoreBackup(restoreButton.dataset.restoreBackup).catch((error) => showToast(error.message));
            return;
        }
        const saveMemoryBtn = event.target.closest("[data-save-memory]");
        if (saveMemoryBtn) {
            saveMemory(saveMemoryBtn.dataset.saveMemory).catch((error) => showToast(error.message));
            return;
        }
        const editModel = event.target.closest("[data-edit-model]");
        if (editModel) {
            openModelDialog(modelEntries().find(model => model.id === editModel.dataset.editModel));
            return;
        }
        const deleteProvider = event.target.closest("[data-delete-provider]");
        if (deleteProvider) {
            const id = deleteProvider.dataset.deleteProvider;
            if (!await showConfirmDialog(t('settings_js.confirm_delete_provider', {name: providerDisplayName(id), count: linkedModelCount(id)}), {danger: true})) return;
            deletedProviderIds.add(id);
            delete settings.providers[id];
            modelEntries()
                .filter((model) => model.provider === id)
                .forEach((model) => deletedModelIds.add(model.id));
            settings.models = modelEntries().filter((model) => model.provider !== id);
            deleteProvider.closest(".provider-item").remove();
            renderDefaultModelOptions($("default-model-input").value);
            renderModels();
            renderSummary();
            return;
        }
        const deleteModel = event.target.closest("[data-delete-model]");
        if (deleteModel) {
            const id = deleteModel.dataset.deleteModel;
            deletedModelIds.add(id);
            settings.models = modelEntries().filter((model) => model.id !== id);
            renderDefaultModelOptions($("default-model-input").value);
            renderModels();
            for (const row of document.querySelectorAll(".provider-item")) {
                row.querySelector("[data-linked-count]").textContent = t("settings_js.linked_models", {count: linkedModelCount(row.dataset.providerId)});
            }
            renderSummary();
            return;
        }
        const deleteMemory = event.target.closest("[data-delete-memory]");
        if (deleteMemory) {
            deleteMemoryFn(deleteMemory.dataset.deleteMemory);
        }
    });
}

bindEvents();
loadAll().catch((error) => showToast(error.message));

if ($("plugins-btn")) $("plugins-btn").addEventListener("click", () => window.location.href = "/plugins-page");
if ($("mcp-services-btn")) $("mcp-services-btn").addEventListener("click", () => window.location.href = "/mcp-services-page");

// 初始化语言选择器。
(function initLanguageSelect() {
    const select = $("language-select");
    if (!select) return;
    select.value = getLocale();
    select.addEventListener("change", () => {
        setLocale(select.value);
    });
    window.addEventListener("locale-changed", () => {
        select.value = getLocale();
        loadAll().catch((error) => showToast(error.message));
    });
})();
