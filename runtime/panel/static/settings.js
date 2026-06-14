const $ = (id) => document.getElementById(id);

let settings = null;
let backups = [];
let backupMeta = {};
let memories = [];  // Loaded from /memories API
let activeSettingsPage = localStorage.getItem("lit_settings_page") || "models";
const deletedProviderIds = new Set();
const deletedModelIds = new Set();

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
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
    $("planning-policy-input").value = settings?.planning_policy || planningPolicyFromLegacyExecutionMode(settings?.execution_mode);
    $("confirmation-policy-input").value = settings?.confirmation_policy || "auto";
    $("backup-enabled-input").checked = backupSettings.enabled !== false;
    $("backup-keep-input").value = backupSettings.keep_rounds || 50;
    $("memory-enabled-input").checked = memorySettings.enabled !== false;
    $("memory-max-active-input").value = Number(memorySettings.max_active ?? 30);
    $("memory-auto-extract-input").checked = memorySettings.auto_extract !== false;
    setDynamicText("settings-path", settings?.settings_path || "");
    showSettingsPage(activeSettingsPage, false);
    renderSummary();
}

function renderDefaultModelOptions() {
    const models = modelEntries();
    $("default-model-input").innerHTML = models.map((model) => `
        <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)} · ${escapeHtml(model.provider || "")}</option>
    `).join("");
    if (models.some((model) => model.id === settings.default_model)) {
        $("default-model-input").value = settings.default_model;
    } else if (models[0]) {
        $("default-model-input").value = models[0].id;
    }
}

function renderProviders() {
    const providers = providerEntries();
    $("provider-list").innerHTML = providers.length ? providers.map((provider) => `
        <div class="settings-item provider-item" data-provider-id="${escapeHtml(provider.id)}">
            <div class="settings-item-head">
                <div class="settings-item-title">
                    <strong>${escapeHtml(provider.name || provider.id)}</strong>
                    <span>${escapeHtml(provider.id)} · ${provider.has_api_key ? `Key ${escapeHtml(provider.api_key_hint)}` : t('settings_js.no_key')} · ${t('settings_js.linked_models', {count: linkedModelCount(provider.id)})}</span>
                </div>
                <button class="secondary-button danger-button" type="button" data-delete-provider="${escapeHtml(provider.id)}">${t('settings_js.remove_provider')}</button>
            </div>
            <div class="settings-inline">
                <div class="settings-form-row">
                    <label>${t('settings_js.provider_name')}</label>
                    <input data-provider-field="name" value="${escapeHtml(provider.name || "")}">
                </div>
                <div class="settings-form-row">
                    <label>${t('settings_js.provider_type')}</label>
                    <select data-provider-field="kind">
                        <option value="openai" ${provider.kind === "openai" ? "selected" : ""}>OpenAI Compatible</option>
                    </select>
                </div>
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
            </div>
        </div>
    `).join("") : `<div class="hint-line">${t('settings_js.no_providers')}</div>`;
}

function renderModels() {
    const models = modelEntries();
    $("model-list").innerHTML = models.length ? models.map((model) => `
        <div class="settings-item model-item" data-model-id="${escapeHtml(model.id)}">
            <div class="settings-item-head">
                <div class="settings-item-title">
                    <strong>${escapeHtml(model.name || model.id)}</strong>
                    <span>${escapeHtml(model.id)} · ${escapeHtml(providerDisplayName(model.provider))} · ${escapeHtml(model.api_model || model.id)}</span>
                </div>
                <button class="secondary-button danger-button" type="button" data-delete-model="${escapeHtml(model.id)}">${t('settings_js.remove_model')}</button>
            </div>
            <div class="settings-inline">
                <div class="settings-form-row">
                    <label>${t('settings_js.display_name')}</label>
                    <input data-model-field="name" value="${escapeHtml(model.name || "")}">
                </div>
                <div class="settings-form-row">
                    <label>${t('settings_js.provider_label')}</label>
                    <select data-model-field="provider">${renderProviderOptions(model.provider)}</select>
                </div>
            </div>
            <div class="settings-inline">
                <div class="settings-form-row">
                    <label>${t('settings_js.api_model_name')}</label>
                    <input data-model-field="api_model" value="${escapeHtml(model.api_model || model.id)}">
                </div>
                <div class="settings-form-row">
                    <label>${t('settings_js.context_window')}</label>
                    <input data-model-field="context_limit" type="number" min="4096" step="1024" value="${Number(model.context_limit || 128000)}">
                </div>
            </div>
            <div class="settings-inline">
                <div class="settings-form-row">
                    <label>${t('settings_js.max_output_tokens')}</label>
                    <input data-model-field="max_output_tokens" type="number" min="0" step="1024" value="${Number(model.max_output_tokens || 0)}">
                </div>
                <div class="settings-form-row">
                    <label>${t('settings_js.output_token_param')}</label>
                    <select data-model-field="output_token_param">
                        <option value="" ${!model.output_token_param ? "selected" : ""}>${t('settings_js.provider_default')}</option>
                        <option value="max_tokens" ${model.output_token_param === "max_tokens" ? "selected" : ""}>max_tokens</option>
                        <option value="max_completion_tokens" ${model.output_token_param === "max_completion_tokens" ? "selected" : ""}>max_completion_tokens</option>
                        <option value="max_output_tokens" ${model.output_token_param === "max_output_tokens" ? "selected" : ""}>max_output_tokens</option>
                    </select>
                </div>
            </div>
            <div class="settings-inline">
                <label class="checkbox-line compact">
                    <input data-model-field="supports_tools" type="checkbox" ${model.supports_tools !== false ? "checked" : ""}>
                    <span>${t('settings_js.support_tools')}</span>
                </label>
                <label class="checkbox-line compact">
                    <input data-model-field="supports_reasoning_effort" type="checkbox" ${model.supports_reasoning_effort ? "checked" : ""}>
                    <span>${t('settings_js.support_reasoning_effort')}</span>
                </label>
            </div>
            <div class="settings-form-row">
                <label>${t('settings_js.thinking_mode')}</label>
                <select data-model-field="thinking_mode">
                    <option value="" ${!model.thinking_mode ? "selected" : ""}>${t('settings_js.thinking_none')}</option>
                    <option value="volcengine" ${model.thinking_mode === "volcengine" ? "selected" : ""}>${t('settings_js.thinking_volcengine')}</option>
                    <option value="qwen" ${model.thinking_mode === "qwen" ? "selected" : ""}>${t('settings_js.thinking_qwen')}</option>
                </select>
                <span class="hint-line">${t('settings_js.thinking_mode_hint')}</span>
            </div>
            <div class="settings-form-row">
                <label>${t('settings_js.model_params')}</label>
                <textarea data-model-field="request_options" placeholder='{"temperature":0.2,"max_tokens":4096}'>${escapeHtml(JSON.stringify(model.request_options || {}, null, 2))}</textarea>
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
    const planMap = { off: t('settings_js.plan_off'), auto: t('settings_js.plan_auto'), always: t('settings_js.plan_always') };
    const confirmMap = { conservative: t('settings_js.confirm_conservative'), auto: t('settings_js.confirm_auto'), aggressive: t('settings_js.confirm_aggressive') };
    const planning = planMap[$("planning-policy-input").value] || t('settings_js.plan_auto');
    const confirmation = confirmMap[$("confirmation-policy-input").value] || t('settings_js.confirm_auto');
    const memoryCount = memoryEntries().filter((item) => item.enabled !== false).length;
    setDynamicText("settings-summary", t('settings_js.summary_text', {
        access: accessText,
        planning,
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

function readJson(text, fallback = {}) {
    const value = String(text || "").trim();
    if (!value) return fallback;
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : fallback;
}

function collectProviders() {
    const providers = {};
    document.querySelectorAll(".provider-item").forEach((item) => {
        const id = item.dataset.providerId;
        providers[id] = {
            name: item.querySelector('[data-provider-field="name"]').value.trim() || id,
            kind: item.querySelector('[data-provider-field="kind"]').value,
            base_url: item.querySelector('[data-provider-field="base_url"]').value.trim(),
            chat_path: item.querySelector('[data-provider-field="chat_path"]').value.trim() || "/chat/completions",
            api_key_required: item.querySelector('[data-provider-field="api_key_required"]').checked,
            request_options: readJson(item.querySelector('[data-provider-field="request_options"]').value, {}),
            enabled: true,
        };
        const apiKey = item.querySelector('[data-provider-field="api_key"]').value.trim();
        if (apiKey) providers[id].api_key = apiKey;
    });
    return providers;
}

function collectModels() {
    const models = [];
    document.querySelectorAll(".model-item").forEach((item) => {
        const id = item.dataset.modelId;
        models.push({
            id,
            name: item.querySelector('[data-model-field="name"]').value.trim() || id,
            provider: item.querySelector('[data-model-field="provider"]').value,
            api_model: item.querySelector('[data-model-field="api_model"]').value.trim() || id,
            context_limit: Number(item.querySelector('[data-model-field="context_limit"]').value || 128000),
            max_output_tokens: Number(item.querySelector('[data-model-field="max_output_tokens"]').value || 0),
            output_token_param: item.querySelector('[data-model-field="output_token_param"]').value,
            supports_tools: item.querySelector('[data-model-field="supports_tools"]').checked,
            supports_reasoning_effort: item.querySelector('[data-model-field="supports_reasoning_effort"]').checked,
            thinking_mode: item.querySelector('[data-model-field="thinking_mode"]').value,
            request_options: readJson(item.querySelector('[data-model-field="request_options"]').value, {}),
            enabled: true,
        });
    });
    return models;
}

function collectMemories() {
    // Memories are now managed via the /memories API, not collected from form
    // This function is kept for backward compat but returns empty
    return [];
}

async function saveSettings() {
    let providers;
    let models;
    try {
        providers = collectProviders();
        models = collectModels();
    } catch (error) {
        showToast(t('settings_js.json_error', {error: error.message}));
        return;
    }
    settings = await api("/settings", {
        method: "POST",
        body: JSON.stringify({
            default_model: $("default-model-input").value,
            access_scope: $("access-scope-input").value,
            planning_policy: $("planning-policy-input").value,
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
            providers,
            models,
            deleted_provider_ids: Array.from(deletedProviderIds),
            deleted_model_ids: Array.from(deletedModelIds),
        }),
    });
    deletedProviderIds.clear();
    deletedModelIds.clear();
    localStorage.setItem("lit_model", settings.default_model || $("default-model-input").value);
    localStorage.setItem("lit_planning_policy", settings.planning_policy || $("planning-policy-input").value);
    localStorage.setItem("lit_confirmation_policy", settings.confirmation_policy || $("confirmation-policy-input").value);
    localStorage.setItem("lit_plan_execution_mode", settings.planning_policy || "auto");
    renderSettings();
    showToast(t('toast.settings_saved'));
}

function planningPolicyFromLegacyExecutionMode(value) {
    return { conservative: "off", auto: "auto", aggressive: "always" }[value] || "auto";
}

async function refreshBackups() {
    const data = await api("/backups");
    backups = data.items || [];
    backupMeta = data || {};
    renderBackups();
}

async function restoreBackup(backupId) {
    if (!backupId) return;
    if (!window.confirm(t('backup.confirm_restore'))) return;
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
    if (!window.confirm(t('backup.confirm_clear'))) return;
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

function addProvider() {
    const id = window.prompt(t('settings_js.provider_id_prompt'));
    const providerId = String(id || "").trim();
    if (!providerId) return;
    if (settings.providers[providerId]) {
        showToast(t('settings_js.provider_exists'));
        return;
    }
    settings.providers[providerId] = {
        id: providerId,
        name: providerId,
        kind: "openai",
        base_url: "",
        chat_path: "/chat/completions",
        api_key_required: true,
        request_options: {},
    };
    deletedProviderIds.delete(providerId);
    activeSettingsPage = "providers";
    renderSettings();
}

function addModel() {
    const id = window.prompt(t('settings_js.model_id_prompt'));
    const modelId = String(id || "").trim();
    if (!modelId) return;
    if (modelEntries().some((model) => model.id === modelId)) {
        showToast(t('settings_js.model_exists'));
        return;
    }
    const provider = providerEntries()[0]?.id || "";
    settings.models.push({
        id: modelId,
        name: modelId,
        provider,
        api_model: modelId,
        context_limit: 128000,
        max_output_tokens: 0,
        output_token_param: "",
        supports_tools: true,
        supports_reasoning_effort: false,
        thinking_mode: "",
        request_options: {},
    });
    deletedModelIds.delete(modelId);
    activeSettingsPage = "models";
    renderSettings();
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
        // Update local memories array
        const idx = memories.findIndex((m) => m.id === memoryId);
        if (idx >= 0) memories[idx] = result;
        showToast(t('settings_js.memory_saved'));
    } catch (error) {
        showToast(t('settings_js.save_failed', {error: error.message}));
    }
}

async function deleteMemoryFn(memoryId) {
    if (!window.confirm(t('settings_js.confirm_delete_memory'))) return;
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
    $("add-provider-btn").addEventListener("click", addProvider);
    $("add-model-btn").addEventListener("click", addModel);
    $("add-memory-btn").addEventListener("click", addMemory);
    $("refresh-backups-btn").addEventListener("click", () => refreshBackups().catch((error) => showToast(error.message)));
    $("restore-latest-backup-btn").addEventListener("click", () => restoreLatestBackup().catch((error) => showToast(error.message)));
    $("clear-backups-btn").addEventListener("click", () => clearBackups().catch((error) => showToast(error.message)));
    $("access-scope-input").addEventListener("change", renderSummary);
    $("planning-policy-input").addEventListener("change", renderSummary);
    $("confirmation-policy-input").addEventListener("change", renderSummary);
    $("memory-filter-input").addEventListener("change", renderMemories);
    document.querySelectorAll("[data-settings-page-button]").forEach((button) => {
        button.addEventListener("click", () => {
            showSettingsPage(button.dataset.settingsPageButton);
        });
    });
    document.addEventListener("click", (event) => {
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
        const deleteProvider = event.target.closest("[data-delete-provider]");
        if (deleteProvider) {
            const id = deleteProvider.dataset.deleteProvider;
            if (!window.confirm(t('settings_js.confirm_delete_provider', {id}))) return;
            deletedProviderIds.add(id);
            delete settings.providers[id];
            modelEntries()
                .filter((model) => model.provider === id)
                .forEach((model) => deletedModelIds.add(model.id));
            settings.models = modelEntries().filter((model) => model.provider !== id);
            renderSettings();
            return;
        }
        const deleteModel = event.target.closest("[data-delete-model]");
        if (deleteModel) {
            const id = deleteModel.dataset.deleteModel;
            deletedModelIds.add(id);
            settings.models = modelEntries().filter((model) => model.id !== id);
            renderSettings();
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

// Language select initialization
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
