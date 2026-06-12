const $ = (id) => document.getElementById(id);

let services = [];
let activeServiceId = "";
let editingServiceId = "";
let didProbePrerequisites = false;

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
    setTimeout(() => toast.remove(), 3200);
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: {"Content-Type": "application/json; charset=utf-8", "Accept-Language": getLocale()},
        ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
}

async function loadServices() {
    const result = await api("/mcp-services");
    services = result.data || [];
    renderAll();
    if (!didProbePrerequisites) {
        didProbePrerequisites = true;
        const candidates = services.filter((service) => (service.prerequisites || []).length);
        if (candidates.length) {
            await Promise.allSettled(candidates.map((service) => api(
                `/mcp-services/${encodeURIComponent(service.id)}/actions`,
                {method: "POST", body: JSON.stringify({action: "check"})},
            )));
            const refreshed = await api("/mcp-services");
            services = refreshed.data || [];
            renderAll();
        }
    }
}

function renderAll() {
    renderSummary();
    renderSidebar();
    renderServices();
}

function renderSummary() {
    const connected = services.filter((service) => service.status?.state === "connected").length;
    const running = services.filter((service) => ["running", "reachable", "connected"].includes(service.status?.state)).length;
    $("mcp-summary").textContent = t("mcp_js.summary", {connected, running, total: services.length});
}

function renderSidebar() {
    const target = $("mcp-service-groups");
    const allActive = activeServiceId ? "" : "active";
    let html = `<button class="plugin-group-item ${allActive}" data-service="">${t("mcp_js.all_services")}</button>`;
    for (const service of services) {
        const state = service.status?.state || "stopped";
        html += `<button class="plugin-group-item ${activeServiceId === service.id ? "active" : ""}" data-service="${escapeHtml(service.id)}">
            <span>${escapeHtml(service.name)}</span><span class="state-dot state-${escapeHtml(state)}"></span>
        </button>`;
    }
    target.innerHTML = html;
    target.querySelectorAll("[data-service]").forEach((button) => {
        button.addEventListener("click", () => {
            activeServiceId = button.dataset.service || "";
            renderAll();
        });
    });
}

function renderServices() {
    const target = $("mcp-service-list");
    const visible = activeServiceId ? services.filter((service) => service.id === activeServiceId) : services;
    if (!visible.length) {
        target.innerHTML = `<div class="empty-state">${t("mcp_js.no_services")}</div>`;
        return;
    }
    target.innerHTML = visible.map(renderServiceCard).join("");
    target.querySelectorAll("[data-action]").forEach((button) => {
        button.addEventListener("click", () => runAction(button.dataset.service, button.dataset.action));
    });
    target.querySelectorAll("[data-edit]").forEach((button) => {
        button.addEventListener("click", () => openEditor(button.dataset.edit));
    });
    target.querySelectorAll("[data-delete]").forEach((button) => {
        button.addEventListener("click", () => deleteService(button.dataset.delete));
    });
    target.querySelectorAll("[data-toggle-enabled]").forEach((button) => {
        button.addEventListener("click", () => toggleServiceEnabled(
            button.dataset.toggleEnabled,
            button.dataset.enabled !== "true",
        ));
    });
}

function renderServiceCard(service) {
    const status = service.status || {};
    const state = status.state || "stopped";
    const transport = service.transport || {};
    const transportDetail = transport.type === "stdio"
        ? [transport.command, ...(transport.args || [])].filter(Boolean).join(" ")
        : transport.url || "";
    const logs = (status.logs || []).slice(-8)
        .map((item) => `${item.time || ""} [${item.level || "info"}] ${item.message || ""}`)
        .join("\n");
    const managesProcess = transport.type === "stdio";
    const installation = service.installation || {};
    const bindings = service.capability_bindings || [];
    const prerequisites = status.prerequisites || [];
    const prerequisitesReady = prerequisites.every((item) => item.ready);
    const serverName = status.server_info?.name || "";
    const canStart = service.enabled && prerequisitesReady && !["running", "connected"].includes(state);
    const canStop = managesProcess && ["running", "connected"].includes(state);
    return `<article class="service-card ${service.enabled ? "" : "disabled"}">
        <div class="service-head">
            <div>
                <div class="service-title-row">
                    <h3 class="service-title">${escapeHtml(service.name)}</h3>
                    <span class="state-badge state-${escapeHtml(state)}"><span class="state-dot"></span>${escapeHtml(t(`mcp_state.${state}`))}</span>
                </div>
                <p class="service-copy">${escapeHtml(service.description || service.id)}</p>
            </div>
        </div>
        <div class="service-meta">
            <span class="service-chip">${escapeHtml(installation.kind || "unknown_source")}</span>
            ${installation.package ? `<span class="service-chip">${escapeHtml(installation.package)}</span>` : ""}
            <span class="service-chip">${escapeHtml(transport.type || "")}</span>
            <span class="service-chip">${escapeHtml(transportDetail)}</span>
            <span class="service-chip">${escapeHtml(t("mcp_js.linked_tools", {count: service.linked_capability_count || 0}))}</span>
            ${status.protocol_version ? `<span class="service-chip">MCP ${escapeHtml(status.protocol_version)}</span>` : ""}
            ${serverName ? `<span class="service-chip">${escapeHtml(serverName)}</span>` : ""}
        </div>
        <div class="service-message">${escapeHtml(status.message || "")}</div>
        ${prerequisites.length ? `<div class="service-prerequisites">${prerequisites.map((item) => `
            <span class="prerequisite-item ${item.ready ? "ready" : "missing"}" title="${escapeHtml(item.message || "")}">
                <span class="state-dot"></span>${escapeHtml(item.label)}
            </span>`).join("")}</div>` : ""}
        ${bindings.length ? `<div class="service-bindings">${bindings.map((binding) => {
            const health = binding.health || "available";
            const title = binding.last_error || `${binding.risk || "unknown"} · ${(binding.effects || []).join(", ")}`;
            return `<span class="tool-chip binding-${escapeHtml(health)}" title="${escapeHtml(title)}"><span class="state-dot"></span>${escapeHtml(binding.remote_name)} → ${escapeHtml(binding.tool_id)}</span>`;
        }).join("")}</div>` : ""}
        ${logs ? `<pre class="service-logs">${escapeHtml(logs)}</pre>` : ""}
        <div class="service-actions">
            <button class="secondary-button" data-service="${escapeHtml(service.id)}" data-action="check">${t("mcp_js.check")}</button>
            <button class="secondary-button" data-toggle-enabled="${escapeHtml(service.id)}" data-enabled="${service.enabled ? "true" : "false"}">${service.enabled ? t("mcp_js.disable_connection") : t("mcp_js.enable_connection")}</button>
            ${managesProcess ? `<button class="primary-button" data-service="${escapeHtml(service.id)}" data-action="start" ${canStart ? "" : "disabled"}>${t("mcp_js.start")}</button>` : ""}
            ${managesProcess ? `<button class="secondary-button" data-service="${escapeHtml(service.id)}" data-action="stop" ${canStop ? "" : "disabled"}>${t("mcp_js.stop")}</button>` : ""}
            ${managesProcess ? `<button class="secondary-button" data-service="${escapeHtml(service.id)}" data-action="restart" ${service.enabled ? "" : "disabled"}>${t("mcp_js.restart")}</button>` : ""}
            <button class="secondary-button" data-edit="${escapeHtml(service.id)}">${t("mcp_js.edit")}</button>
            <button class="secondary-button" data-delete="${escapeHtml(service.id)}">${t("mcp_js.delete")}</button>
        </div>
    </article>`;
}

async function toggleServiceEnabled(serviceId, enabled) {
    const service = services.find((item) => item.id === serviceId);
    if (!service) return;
    const transport = service.transport || {};
    const payload = {
        name: service.name,
        description: service.description,
        enabled,
        installation: service.installation || {},
        transport: transport.type === "stdio"
            ? {
                type: transport.type,
                command: transport.command,
                args: transport.args || [],
                cwd: transport.cwd || "",
            }
            : {
                type: transport.type,
                url: transport.url,
                health_url: transport.health_url || "",
            },
        lifecycle: service.lifecycle || {},
        permissions: service.permissions || {},
        tool_policies: service.tool_policies || {},
        prerequisites: service.prerequisites || [],
    };
    try {
        await api(`/mcp-services/${encodeURIComponent(serviceId)}`, {
            method: "PUT",
            body: JSON.stringify(payload),
        });
        await runAction(serviceId, "check");
    } catch (error) {
        showToast(error.message);
    }
}

async function runAction(serviceId, action) {
    try {
        await api(`/mcp-services/${encodeURIComponent(serviceId)}/actions`, {
            method: "POST",
            body: JSON.stringify({action}),
        });
        await loadServices();
    } catch (error) {
        showToast(error.message);
    }
}

async function deleteService(serviceId) {
    if (!window.confirm(t("mcp_js.confirm_delete", {id: serviceId}))) return;
    try {
        await api(`/mcp-services/${encodeURIComponent(serviceId)}`, {method: "DELETE"});
        if (activeServiceId === serviceId) activeServiceId = "";
        await loadServices();
    } catch (error) {
        showToast(error.message);
    }
}

function openEditor(serviceId = "") {
    editingServiceId = serviceId;
    const service = services.find((item) => item.id === serviceId);
    const transport = service?.transport || {type: "stdio"};
    $("mcp-id").value = service?.id || "";
    $("mcp-id").disabled = Boolean(service);
    $("mcp-name").value = service?.name || "";
    $("mcp-description").value = service?.description || "";
    $("mcp-enabled").value = String(Boolean(service?.enabled));
    $("mcp-installation-kind").value = service?.installation?.kind || (transport.type === "stdio" ? "local_command" : "remote_endpoint");
    $("mcp-package").value = service?.installation?.package || "";
    $("mcp-transport").value = transport.type || "stdio";
    $("mcp-command").value = transport.command || "";
    $("mcp-args").value = JSON.stringify(transport.args || [], null, 2);
    $("mcp-cwd").value = transport.cwd || "";
    $("mcp-env").value = service ? "" : "{}";
    $("mcp-url").value = transport.url || "";
    $("mcp-health-url").value = transport.health_url || "";
    $("mcp-headers").value = service ? "" : "{}";
    const permissions = service?.permissions || {};
    $("mcp-permission-filesystem").value = permissions.filesystem || "workspace";
    $("mcp-permission-network").value = permissions.network || "confirm_each";
    $("mcp-permission-external-state").value = permissions.external_state || "confirm_each";
    $("mcp-permission-arbitrary-code").value = permissions.arbitrary_code || "confirm_each";
    toggleTransportFields();
    toggleInstallationFields();
    $("mcp-dialog").showModal();
}

function toggleTransportFields() {
    const stdio = $("mcp-transport").value === "stdio";
    document.querySelectorAll(".stdio-field").forEach((field) => field.hidden = !stdio);
    document.querySelectorAll(".endpoint-field").forEach((field) => field.hidden = stdio);
}

function handleTransportChange() {
    toggleTransportFields();
    if (!editingServiceId) {
        $("mcp-installation-kind").value = $("mcp-transport").value === "stdio"
            ? "local_command"
            : "remote_endpoint";
        toggleInstallationFields();
    }
}

function toggleInstallationFields() {
    const packageRunner = $("mcp-installation-kind").value === "package_runner";
    document.querySelectorAll(".package-field").forEach((field) => field.hidden = !packageRunner);
}

function parseJsonField(id, fallback) {
    const text = $(id).value.trim();
    if (!text) return fallback;
    return JSON.parse(text);
}

async function saveService(event) {
    event.preventDefault();
    try {
        const type = $("mcp-transport").value;
        const transport = type === "stdio"
            ? {
                type,
                command: $("mcp-command").value.trim(),
                args: parseJsonField("mcp-args", []),
                cwd: $("mcp-cwd").value.trim(),
            }
            : {
                type,
                url: $("mcp-url").value.trim(),
                health_url: $("mcp-health-url").value.trim(),
            };
        if (type === "stdio" && $("mcp-env").value.trim()) {
            transport.env = parseJsonField("mcp-env", {});
        }
        if (type !== "stdio" && $("mcp-headers").value.trim()) {
            transport.headers = parseJsonField("mcp-headers", {});
        }
        const payload = {
            id: $("mcp-id").value.trim(),
            name: $("mcp-name").value.trim(),
            description: $("mcp-description").value.trim(),
            enabled: $("mcp-enabled").value === "true",
            installation: {
                kind: $("mcp-installation-kind").value,
                package: $("mcp-package").value.trim(),
                managed: false,
            },
            transport,
            permissions: {
                filesystem: $("mcp-permission-filesystem").value,
                network: $("mcp-permission-network").value,
                external_state: $("mcp-permission-external-state").value,
                arbitrary_code: $("mcp-permission-arbitrary-code").value,
            },
        };
        const path = editingServiceId ? `/mcp-services/${encodeURIComponent(editingServiceId)}` : "/mcp-services";
        await api(path, {method: editingServiceId ? "PUT" : "POST", body: JSON.stringify(payload)});
        $("mcp-dialog").close();
        await loadServices();
    } catch (error) {
        showToast(error.message);
    }
}

$("back-btn").addEventListener("click", () => window.location.href = "/");
$("plugins-btn").addEventListener("click", () => window.location.href = "/plugins-page");
$("refresh-mcp-btn").addEventListener("click", () => loadServices().catch((error) => showToast(error.message)));
$("add-mcp-btn").addEventListener("click", () => openEditor());
$("cancel-mcp-btn").addEventListener("click", () => $("mcp-dialog").close());
$("mcp-transport").addEventListener("change", handleTransportChange);
$("mcp-installation-kind").addEventListener("change", toggleInstallationFields);
$("mcp-form").addEventListener("submit", saveService);

loadServices().catch((error) => showToast(error.message));
