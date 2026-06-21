const $ = (id) => document.getElementById(id);

const state = {
    automations: [],
    workspaces: [],
    settings: null,
    selectedId: "",
};

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
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
        headers: {"Content-Type": "application/json; charset=utf-8", "Accept-Language": getLocale()},
        ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
        throw new Error(payload.error || response.statusText);
    }
    return payload.data ?? payload;
}

function navigate(url) {
    window.location.href = url;
}

async function loadAll() {
    const [automations, workspaces, settings] = await Promise.all([
        api("/automations"),
        api("/workspaces"),
        api("/settings"),
    ]);
    state.automations = automations || [];
    state.workspaces = workspaces || [];
    state.settings = settings || {};
    if (!state.selectedId && state.automations.length) {
        state.selectedId = state.automations[0].id;
    }
    renderWorkspaceOptions();
    renderModelOptions();
    renderList();
    renderForm();
    renderSummary();
}

function renderSummary() {
    const active = state.automations.filter((item) => item.state === "active").length;
    $("automation-summary").textContent = t("automation_page.summary", {
        active,
        total: state.automations.length,
    });
}

function renderWorkspaceOptions() {
    const select = $("automation-workspace");
    select.innerHTML = state.workspaces.length
        ? state.workspaces.map((workspace) =>
            `<option value="${escapeHtml(workspace.id)}">${escapeHtml(workspace.name || workspace.path || workspace.id)}</option>`
        ).join("")
        : `<option value="">${escapeHtml(t("automation_page.no_workspace"))}</option>`;
}

function renderModelOptions() {
    const select = $("automation-model");
    const models = state.settings?.models || [];
    const defaultModel = state.settings?.default_model || "";
    select.innerHTML = models.length
        ? models.map((model) =>
            `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>`
        ).join("")
        : `<option value="${escapeHtml(defaultModel)}">${escapeHtml(defaultModel || t("automation_page.default_model"))}</option>`;
}

function renderList() {
    const container = $("automation-list");
    if (!state.automations.length) {
        container.innerHTML = `<div class="automation-item-meta">${escapeHtml(t("automation_page.empty_short"))}</div>`;
        return;
    }
    container.innerHTML = state.automations.map((item) => {
        const trigger = triggerLabel(item);
        const active = item.id === state.selectedId ? " active" : "";
        return `
            <button class="automation-item${active}" type="button" data-automation-id="${escapeHtml(item.id)}">
                <div class="automation-item-title">
                    <span class="automation-dot ${escapeHtml(item.state || "draft")}"></span>
                    <span>${escapeHtml(item.name || t("automation_page.untitled"))}</span>
                </div>
                <div class="automation-item-meta">${escapeHtml(trigger)}</div>
            </button>
        `;
    }).join("");
}

function selectedAutomation() {
    return state.automations.find((item) => item.id === state.selectedId) || null;
}

function renderForm() {
    const item = selectedAutomation();
    const hasItem = Boolean(item);
    $("automation-empty").classList.toggle("hidden", hasItem);
    $("delete-btn").disabled = !hasItem;
    $("run-now-btn").disabled = false;

    const payload = item || defaultAutomation();
    const template = payload.task_template || {};
    const trigger = payload.trigger || {};

    $("automation-name").value = payload.name || "";
    $("automation-goal").value = template.goal || "";
    setSelectValue("automation-workspace", template.workspace_id || firstWorkspaceId());
    setSelectValue("automation-model", template.model || state.settings?.default_model || "");
    setSelectValue("automation-trigger-kind", trigger.kind || "manual");
    setSelectValue("automation-state", payload.state || "active");
    $("automation-run-at").value = toLocalInputValue(trigger.run_at || "");
    $("automation-time-of-day").value = trigger.time_of_day || "";
    $("automation-interval-minutes").value = String(Math.max(1, Math.round((trigger.interval_seconds || 3600) / 60)));
    setSelectValue("automation-weekday", (trigger.days_of_week || [])[0] || "mon");
    setSelectValue("automation-planning", template.planning_policy || state.settings?.planning_policy || "auto");
    setSelectValue("automation-confirmation", template.confirmation_policy || state.settings?.confirmation_policy || "auto");
    setSelectValue("automation-access", template.access_scope || state.settings?.access_scope || "project_only");
    setSelectValue("automation-concurrency", payload.concurrency_policy || "skip_if_running");
    updateTriggerFields();
    renderPreview(payload);
}

function renderPreview(item) {
    const preview = $("automation-preview");
    if (!item) {
        preview.innerHTML = "";
        return;
    }
    const template = item.task_template || {};
    const workspace = state.workspaces.find((value) => value.id === template.workspace_id);
    const rows = [
        [t("automation_page.name"), item.name || ""],
        [t("automation_page.goal"), template.goal || ""],
        [t("automation_page.workspace"), workspace?.name || workspace?.path || template.workspace_id || ""],
        [t("automation_page.trigger_kind"), triggerLabel(item)],
        [t("automation_page.state"), stateLabel(item.state)],
        [t("automation_page.last_run"), item.last_run_id || t("automation_page.none")],
    ];
    preview.innerHTML = rows.map(([label, value]) => `
        <div class="automation-preview-row">
            <span>${escapeHtml(label)}</span>
            <span>${escapeHtml(value)}</span>
        </div>
    `).join("");
}

function defaultAutomation() {
    return {
        id: "",
        name: "",
        state: "active",
        concurrency_policy: "skip_if_running",
        trigger: {kind: "manual", interval_seconds: 3600, days_of_week: ["mon"], time_of_day: "09:00"},
        task_template: {
            goal: "",
            workspace_id: firstWorkspaceId(),
            model: state.settings?.default_model || "",
            planning_policy: state.settings?.planning_policy || "auto",
            confirmation_policy: state.settings?.confirmation_policy || "auto",
            access_scope: state.settings?.access_scope || "project_only",
        },
    };
}

function firstWorkspaceId() {
    return state.workspaces[0]?.id || "";
}

function setSelectValue(id, value) {
    const select = $(id);
    if (!select) return;
    select.value = value;
    if (select.value !== value && select.options.length) {
        select.selectedIndex = 0;
    }
}

function formPayload() {
    const triggerKind = $("automation-trigger-kind").value || "manual";
    const minutes = Math.max(1, Number.parseInt($("automation-interval-minutes").value || "60", 10));
    const trigger = {
        kind: triggerKind,
        timezone: "local",
        run_at: "",
        interval_seconds: 0,
        days_of_week: [],
        time_of_day: "",
    };
    if (triggerKind === "once") {
        trigger.run_at = fromLocalInputValue($("automation-run-at").value);
    } else if (triggerKind === "interval") {
        trigger.interval_seconds = minutes * 60;
    } else if (triggerKind === "daily") {
        trigger.time_of_day = $("automation-time-of-day").value || "";
    } else if (triggerKind === "weekly") {
        trigger.days_of_week = [$("automation-weekday").value || "mon"];
        trigger.time_of_day = $("automation-time-of-day").value || "";
    }
    return {
        name: $("automation-name").value.trim(),
        state: $("automation-state").value || "active",
        concurrency_policy: $("automation-concurrency").value || "skip_if_running",
        trigger,
        task_template: {
            goal: $("automation-goal").value.trim(),
            workspace_id: $("automation-workspace").value || "",
            model: $("automation-model").value || "",
            planning_policy: $("automation-planning").value || "auto",
            confirmation_policy: $("automation-confirmation").value || "auto",
            access_scope: $("automation-access").value || "project_only",
        },
    };
}

function updateTriggerFields() {
    const kind = $("automation-trigger-kind")?.value || "manual";
    document.querySelectorAll("[data-trigger-field]").forEach((field) => {
        const visibleKinds = String(field.getAttribute("data-trigger-field") || "").split(/\s+/);
        field.classList.toggle("hidden", !visibleKinds.includes(kind));
    });
}

async function saveAutomation(event) {
    event?.preventDefault();
    const payload = formPayload();
    if (!payload.task_template.goal) {
        showToast(t("automation_page.goal_required"));
        return;
    }
    const id = state.selectedId;
    const saved = id
        ? await api(`/automations/${encodeURIComponent(id)}`, {method: "PUT", body: JSON.stringify(payload)})
        : await api("/automations", {method: "POST", body: JSON.stringify(payload)});
    state.selectedId = saved.id;
    showToast(t("automation_page.saved"));
    await loadAll();
}

async function deleteAutomation() {
    const item = selectedAutomation();
    if (!item) return;
    if (!confirm(t("automation_page.confirm_delete"))) return;
    await api(`/automations/${encodeURIComponent(item.id)}`, {method: "DELETE"});
    state.selectedId = "";
    showToast(t("automation_page.deleted"));
    await loadAll();
}

async function runNow() {
    if (!state.selectedId) {
        await saveAutomation();
    }
    const item = selectedAutomation();
    if (!item) return;
    const data = await api(`/automations/${encodeURIComponent(item.id)}/actions`, {
        method: "POST",
        body: JSON.stringify({action: "trigger"}),
    });
    if (data.prepared_run) {
        localStorage.setItem("lit_pending_prepared_run", JSON.stringify(data.prepared_run));
        navigate("/?start_prepared=1");
    }
}

function newAutomation() {
    state.selectedId = "";
    renderList();
    renderForm();
    $("automation-name").focus();
}

function triggerLabel(item) {
    const trigger = item?.trigger || {};
    const kind = trigger.kind || "manual";
    if (kind === "manual") return t("automation_page.trigger_manual");
    if (kind === "once") return trigger.run_at ? `${t("automation_page.trigger_once")} · ${formatDate(trigger.run_at)}` : t("automation_page.trigger_once");
    if (kind === "interval") return t("automation_page.trigger_interval_value", {minutes: Math.max(1, Math.round((trigger.interval_seconds || 3600) / 60))});
    if (kind === "daily") return `${t("automation_page.trigger_daily")} · ${trigger.time_of_day || "--:--"}`;
    if (kind === "weekly") return `${t("automation_page.trigger_weekly")} · ${weekdayLabel((trigger.days_of_week || [])[0])} ${trigger.time_of_day || "--:--"}`;
    return kind;
}

function stateLabel(value) {
    return {
        active: t("automation_page.state_active"),
        paused: t("automation_page.state_paused"),
        disabled: t("automation_page.state_disabled"),
        draft: t("automation_page.state_draft"),
    }[value] || value || "";
}

function weekdayLabel(value) {
    return {
        mon: t("automation_page.weekday_mon"),
        tue: t("automation_page.weekday_tue"),
        wed: t("automation_page.weekday_wed"),
        thu: t("automation_page.weekday_thu"),
        fri: t("automation_page.weekday_fri"),
        sat: t("automation_page.weekday_sat"),
        sun: t("automation_page.weekday_sun"),
    }[value] || value || "";
}

function formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function toLocalInputValue(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function fromLocalInputValue(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

document.addEventListener("click", async (event) => {
    const item = event.target.closest("[data-automation-id]");
    if (item) {
        state.selectedId = item.dataset.automationId || "";
        renderList();
        renderForm();
    }
});

$("automation-form")?.addEventListener("submit", saveAutomation);
$("automation-trigger-kind")?.addEventListener("change", updateTriggerFields);
$("new-automation-btn")?.addEventListener("click", newAutomation);
$("reset-btn")?.addEventListener("click", renderForm);
$("delete-btn")?.addEventListener("click", deleteAutomation);
$("run-now-btn")?.addEventListener("click", runNow);
$("refresh-btn")?.addEventListener("click", () => loadAll().catch((error) => showToast(error.message)));
$("back-btn")?.addEventListener("click", () => navigate("/"));
$("plugins-btn")?.addEventListener("click", () => navigate("/plugins-page"));
$("mcp-services-btn")?.addEventListener("click", () => navigate("/mcp-services-page"));

loadAll().catch((error) => showToast(error.message));
