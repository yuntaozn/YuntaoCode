const state = {
    backendUrl: localStorage.getItem("lit_backend_url") || "http://localhost:8088",
    backendToken: localStorage.getItem("lit_backend_token") || "",
    backendUser: localStorage.getItem("lit_backend_user") || "",
    model: localStorage.getItem("lit_model") || "doubao-seed-2-0-pro-260215",
    workspaces: [],
    conversations: [],
    tools: [],
    plugins: [],
    backups: [],
    sourceUpdate: {
        status: "idle",
        data: null,
        error: "",
    },
    activeRuns: [],
    recentTasks: [],
    taskHistory: {
        query: "",
        page: 1,
        pageSize: 8,
        summaries: [],
        total: 0,
        activeWorkbenchRunId: "",
    },
    pendingRunLaunch: null,
    pinnedWorkspaceIds: loadPinnedWorkspaceIds(),
    openWorkspaceMenuId: "",
    accessScope: loadAccessScope(),
    planningPolicy: loadPlanningPolicy(),
    confirmationPolicy: loadConfirmationPolicy(),
    settings: null,
    currentWorkspaceId: localStorage.getItem("lit_workspace_id") || "",
    currentConversationId: localStorage.getItem("lit_conversation_id") || "",
    currentMessages: [],
    activeStreams: new Map(),
    locallyStoppedRunIds: new Set(),
    pendingComposerSubmits: new Set(),
    submitSeq: 0,
    isSending: false,
    abortController: null,
    pendingAttachments: [],
    contextTokens: 0,
    contextLimit: 0,
    search: "",
    mention: {
        active: false,
        start: -1,
        end: -1,
        query: "",
        candidates: [],
        filesWorkspaceId: "",
        files: [],
    },
};

const $ = (id) => document.getElementById(id);

function rememberCurrentPanelState() {
    if (state.currentWorkspaceId) {
        localStorage.setItem("lit_workspace_id", state.currentWorkspaceId);
    }
    if (state.currentConversationId) {
        localStorage.setItem("lit_conversation_id", state.currentConversationId);
    }
}

function loadPinnedWorkspaceIds() {
    try {
        const value = JSON.parse(localStorage.getItem("lit_pinned_workspace_ids") || "[]");
        return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
    } catch {
        return [];
    }
}

function savePinnedWorkspaceIds() {
    localStorage.setItem("lit_pinned_workspace_ids", JSON.stringify(state.pinnedWorkspaceIds));
}

function normalizePlanningPolicy(value) {
    return ["off", "auto", "always"].includes(value) ? value : "auto";
}

function normalizeConfirmationPolicy(value) {
    return ["conservative", "auto", "aggressive"].includes(value) ? value : "auto";
}

function normalizeAccessScope(value) {
    return ["project_only", "full_local"].includes(value) ? value : "project_only";
}

function loadAccessScope() {
    return normalizeAccessScope(localStorage.getItem("lit_access_scope") || "project_only");
}

function loadPlanningPolicy() {
    const stored = localStorage.getItem("lit_planning_policy");
    if (stored) return normalizePlanningPolicy(stored);
    return "auto";
}

function loadConfirmationPolicy() {
    return normalizeConfirmationPolicy(localStorage.getItem("lit_confirmation_policy") || "auto");
}

function headers() {
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Language": getLocale(),
    };
}

function isConversationStreaming(conversationId = state.currentConversationId) {
    return Boolean(conversationId && state.activeStreams.has(conversationId));
}

function composerSubmitKey(conversationId = state.currentConversationId) {
    if (conversationId) return `conversation:${conversationId}`;
    return `workspace:${state.currentWorkspaceId || "unassigned"}`;
}

function isComposerSubmitPending(conversationId = state.currentConversationId) {
    return state.pendingComposerSubmits.has(composerSubmitKey(conversationId));
}

function hasActiveStreams() {
    return state.activeStreams.size > 0;
}

function hasActiveRuns() {
    return state.activeRuns.some(isRunActive);
}

function hasActiveWork() {
    return hasActiveStreams() || hasActiveRuns();
}

function isRunActive(run) {
    return ["running", "waiting_confirmation", "paused"].includes(String(run?.status || ""));
}

function activeRunsForConversation(conversationId) {
    if (!conversationId) return [];
    const runs = state.activeRuns.filter((run) => isRunActive(run) && run.conversation_id === conversationId);
    const activeStream = state.activeStreams.get(conversationId);
    const streamRunId = activeStream?.runId || `stream:${conversationId}`;
    if (activeStream && isRunActive(activeStream) && !runs.some((run) => run.id === streamRunId)) {
        runs.push({
            id: streamRunId,
            conversation_id: conversationId,
            workspace_id: activeStream.workspaceId || "",
            status: activeStream.status || "running",
            stage: activeStream.stage || "streaming",
            message: activeStream.message || t('status.executing'),
            updated_at: activeStream.updatedAt || new Date().toISOString(),
        });
    }
    return runs.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

function activeRunsForWorkspace(workspaceId) {
    if (!workspaceId) return [];
    const runs = state.activeRuns.filter((run) => isRunActive(run) && run.workspace_id === workspaceId);
    const seen = new Set(runs.map((run) => run.id).filter(Boolean));
    for (const [conversationId, activeStream] of state.activeStreams) {
        const conversation = state.conversations.find((item) => item.id === conversationId);
        const streamWorkspaceId = activeStream?.workspaceId || conversation?.workspace_id || "";
        const streamRunId = activeStream?.runId || `stream:${conversationId}`;
        if (streamWorkspaceId === workspaceId && isRunActive(activeStream) && !seen.has(streamRunId)) {
            runs.push({
                id: streamRunId,
                conversation_id: conversationId,
                workspace_id: workspaceId,
                status: activeStream?.status || "running",
                stage: activeStream?.stage || "streaming",
                message: activeStream?.message || t('status.executing'),
                updated_at: activeStream?.updatedAt || new Date().toISOString(),
            });
        }
    }
    return runs.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
}

function latestActiveRunForConversation(conversationId) {
    const runs = activeRunsForConversation(conversationId);
    return runs.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0] || null;
}

function activeRunLabel(run) {
    if (String(run?.status || "") === "waiting_confirmation") {
        return t('status.waiting_confirm');
    }
    if (String(run?.status || "") === "paused") {
        return t('tasks.paused');
    }
    const message = String(run?.message || "").trim();
    const stage = String(run?.stage || "").trim();
    return message || stage || t('conv.running');
}

function formatRunUpdated(run) {
    if (String(run?.status || "") === "waiting_confirmation") {
        return t('status.confirm_pause');
    }
    const updated = Date.parse(run?.updated_at || "");
    if (!Number.isFinite(updated)) return "";
    const seconds = Math.max(0, Math.floor((Date.now() - updated) / 1000));
    return seconds < 3 ? t('status.connection_alive') : t('status.no_progress_for', {time: formatElapsed(seconds)});
}

function runDotMarkup(runs, fallbackActive = false) {
    const activeRuns = Array.isArray(runs) ? runs.filter(isRunActive) : [];
    if (!activeRuns.length && !fallbackActive) return "";
    const waitingConfirm = activeRuns.some((run) => String(run?.status || "") === "waiting_confirmation");
    const paused = activeRuns.some((run) => String(run?.status || "") === "paused");
    const title = waitingConfirm ? t('status.waiting_confirm') : (paused ? t('tasks.paused') : t('conv.running'));
    return `<span class="run-dot ${waitingConfirm ? "waiting" : ""} ${paused ? "paused" : ""}" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"></span>`;
}

async function refreshActiveRuns() {
    const currentConversationId = state.currentConversationId;
    const hadPersistentRun = Boolean(
        currentConversationId
        && !state.activeStreams.has(currentConversationId)
        && state.activeRuns.some((run) => isRunActive(run) && run.conversation_id === currentConversationId)
    );
    try {
        const [running, waiting, paused] = await Promise.all([
            api("/runs?status=running"),
            api("/runs?status=waiting_confirmation"),
            api("/runs?status=paused"),
        ]);
        const merged = [...(running || []), ...(waiting || []), ...(paused || [])]
            .filter((run) => !state.locallyStoppedRunIds.has(run?.id || ""));
        const byId = new Map();
        for (const run of merged) {
            if (run?.id) byId.set(run.id, run);
        }
        state.activeRuns = Array.from(byId.values());
        renderWorkspaces();
        renderConversations();
        renderCurrentWorkspace();
        refreshComposerState();
        syncCurrentConversationStreamStatus();
        const hasPersistentRun = Boolean(
            currentConversationId
            && !state.activeStreams.has(currentConversationId)
            && state.activeRuns.some((run) => isRunActive(run) && run.conversation_id === currentConversationId)
        );
        if (currentConversationId && hasPersistentRun && !hasPersistentRunPlaceholder(currentConversationId)) {
            renderMessages(withPersistentRunPlaceholder({
                id: currentConversationId,
                messages: state.currentMessages,
            }));
        }
        if (currentConversationId && hadPersistentRun && !hasPersistentRun && !state.activeStreams.has(currentConversationId)) {
            await loadConversation(currentConversationId);
        }
    } catch (error) {
        console.warn("refreshActiveRuns failed:", error);
    }
}

function syncPendingConfirmationBar() {
    syncCurrentConversationStreamStatus();
}

function syncPersistentRunStatusBar() {
    const statusBar = $("streaming-status-bar");
    const statusText = $("streaming-status-text");
    const statusElapsed = $("streaming-status-elapsed");
    const statusActions = $("status-bar-actions");
    if (!statusBar || !statusText || !statusActions) return;
    if (!state.currentConversationId || state.activeStreams.has(state.currentConversationId)) {
        return;
    }
    const run = latestActiveRunForConversation(state.currentConversationId);
    if (!run) {
        statusActions.classList.add("hidden");
        statusBar.classList.add("hidden");
        return;
    }
    const waitingConfirmation = String(run.status || "") === "waiting_confirmation";
    const message = activeRunLabel(run);
    statusBar.classList.remove("hidden");
    statusActions.classList.toggle("hidden", !waitingConfirmation);
    statusText.textContent = message;
    statusText.title = message;
    if (statusElapsed) statusElapsed.textContent = waitingConfirmation ? "" : formatRunUpdated(run);
}

async function refreshTaskHistory() {
    if (!state.currentWorkspaceId) {
        state.recentTasks = [];
        state.taskHistory.summaries = [];
        state.taskHistory.total = 0;
        renderTaskHistory();
        return;
    }
    state.taskHistory.summaries = await api(`/tasks?workspace_id=${encodeURIComponent(state.currentWorkspaceId)}`) || [];
    await loadTaskHistoryPage();
}

function filteredTaskHistorySummaries() {
    const query = state.taskHistory.query.trim().toLowerCase();
    const items = Array.isArray(state.taskHistory.summaries) ? state.taskHistory.summaries : [];
    if (!query) return items;
    return items.filter((task) => {
        const haystack = [
            task.goal,
            task.state,
            task.kind,
            task.id,
            task.current_run_id,
        ].map((item) => String(item || "").toLowerCase()).join(" ");
        return haystack.includes(query);
    });
}

function taskHistoryPageCount() {
    return Math.max(1, Math.ceil(state.taskHistory.total / state.taskHistory.pageSize));
}

function clampTaskHistoryPage() {
    const pageCount = taskHistoryPageCount();
    state.taskHistory.page = Math.min(Math.max(1, Number(state.taskHistory.page || 1)), pageCount);
}

async function loadTaskHistoryPage() {
    const filtered = filteredTaskHistorySummaries();
    state.taskHistory.total = filtered.length;
    clampTaskHistoryPage();
    const start = (state.taskHistory.page - 1) * state.taskHistory.pageSize;
    const pageSummaries = filtered.slice(start, start + state.taskHistory.pageSize);
    const details = await Promise.all(
        pageSummaries.map((task) => api(`/tasks/${encodeURIComponent(task.id)}`)),
    );
    state.recentTasks = details;
    renderTaskHistory();
}

function renderTaskHistory() {
    const list = $("task-history-list");
    if (!list) return;
    renderTaskHistoryControls();
    const hasSummaries = Boolean(state.taskHistory.summaries.length);
    if (!state.recentTasks.length) {
        list.innerHTML = `<div class="task-history-empty">${escapeHtml(hasSummaries ? t('tasks.no_match') : t('tasks.empty'))}</div>`;
        return;
    }
    list.innerHTML = state.recentTasks.map((task) => {
        const runs = Array.isArray(task.runs) ? task.runs : [];
        const runRows = runs.map((run) => {
            const status = String(run.status || "");
            const canPause = ["running", "waiting_confirmation"].includes(status);
            const canResume = status === "paused";
            const canStart = status === "created";
            return `
                <div class="task-run-row">
                    <div class="task-run-main">
                        <strong>#${Number(run.attempt || 1)} ${escapeHtml(status)}</strong>
                        <span>${escapeHtml(run.message || run.stage || "")}</span>
                    </div>
                    <div class="task-run-actions">
                        ${canPause ? `<button type="button" data-run-action="pause" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.pause'))}</button>` : ""}
                        ${canResume ? `<button type="button" data-run-action="resume" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.resume_paused'))}</button>` : ""}
                        ${canStart ? `<button type="button" data-run-action="start" data-run-id="${escapeHtml(run.id)}" data-task-id="${escapeHtml(task.id)}" data-conversation-id="${escapeHtml(run.conversation_id || task.conversation_id || "")}" data-goal="${escapeHtml(task.goal || run.user_content || "")}">${escapeHtml(t('tasks.start'))}</button>` : ""}
                        <button type="button" data-run-action="export_fixture" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.export_fixture'))}</button>
                        <button type="button" data-run-action="replay" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.replay'))}</button>
                        <button type="button" data-run-action="workbench" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.workbench'))}</button>
                        <button type="button" data-run-action="export_diagnostic" data-run-id="${escapeHtml(run.id)}">${escapeHtml(t('tasks.export_diagnostic'))}</button>
                    </div>
                </div>
            `;
        }).join("");
        return `
            <section class="task-history-item">
                <div class="task-history-head">
                    <strong>${escapeHtml(task.goal || t('tasks.untitled'))}</strong>
                    <span>${escapeHtml(task.state || "")} · ${Number(task.run_count || runs.length || 0)} Run</span>
                </div>
                <div class="task-run-list">${runRows || `<div class="task-history-empty">${escapeHtml(t('tasks.no_runs'))}</div>`}</div>
            </section>
        `;
    }).join("");
}

function renderTaskHistoryControls() {
    const input = $("task-history-search-input");
    if (input && input.value !== state.taskHistory.query) {
        input.value = state.taskHistory.query;
    }
    const pageCount = taskHistoryPageCount();
    const total = state.taskHistory.total;
    const info = $("task-history-page-info");
    if (info) {
        info.textContent = t('tasks.page_info', {
            page: state.taskHistory.page,
            pages: pageCount,
            total,
        });
    }
    const prev = $("task-history-prev-btn");
    const next = $("task-history-next-btn");
    if (prev) prev.disabled = state.taskHistory.page <= 1;
    if (next) next.disabled = state.taskHistory.page >= pageCount;
}

async function runTaskHistoryAction(action, runId, button, payload = {}) {
    if (action === "start") {
        await startPreparedRun({
            id: runId,
            task_id: button.dataset.taskId || "",
            conversation_id: button.dataset.conversationId || "",
            goal: button.dataset.goal || "",
        });
        return;
    }
    const data = await api(`/runs/${encodeURIComponent(runId)}/actions`, {
        method: "POST",
        body: JSON.stringify({ action, ...payload }),
    });
    if (action === "workbench") {
        renderRunWorkbench(data);
    } else if (action === "open_artifact") {
        showToast(t('tasks.artifact_opened'));
    } else if (action === "runbook") {
        const output = $("task-runbook-output");
        output.textContent = JSON.stringify(data, null, 2);
        output.classList.remove("hidden");
    } else if (action === "export_diagnostic") {
        downloadJson(data.filename || `yuntaocode-diagnostic-${runId}.json`, data);
        showToast(t('tasks.diagnostic_exported'));
    } else if (action === "export_fixture") {
        downloadJson(data.filename || `yuntaocode-experience-sample-${runId}.json`, data);
        showToast(t('tasks.fixture_exported'));
    } else if (action === "replay" || (action === "resume" && data?.prepared_run)) {
        showToast(t('tasks.prepared'));
    }
    if (!["export_diagnostic", "export_fixture", "open_artifact"].includes(action)) {
        await Promise.all([refreshActiveRuns(), refreshTaskHistory()]);
    }
}

function renderRunWorkbench(workbench) {
    const container = $("task-workbench");
    if (!container) return;
    $("task-runbook-output")?.classList.add("hidden");
    const run = workbench?.run || {};
    const task = workbench?.task || {};
    const status = workbench?.status || {};
    const artifacts = Array.isArray(workbench?.artifacts) ? workbench.artifacts : [];
    const verification = Array.isArray(workbench?.verification) ? workbench.verification : [];
    const risks = Array.isArray(workbench?.risks) ? workbench.risks : [];
    const failures = Array.isArray(workbench?.failures) ? workbench.failures : [];
    const audit = workbench?.audit || {};
    const plan = workbench?.plan || {};
    const workspace = workbench?.workspace || {};
    const contextEvidence = workbench?.context_evidence || {};
    const contextAudit = workbench?.context_audit || {};
    const verificationClosure = workbench?.verification_closure || {};
    const visualVerification = workbench?.visual_verification || {};
    const debugAudit = workbench?.debug_audit || {};
    const contextPack = workbench?.context_pack || {};
    const completionDecisions = Array.isArray(workbench?.completion_decisions) ? workbench.completion_decisions : [];
    const modelCalls = Array.isArray(workbench?.model_calls) ? workbench.model_calls : [];
    const timeline = Array.isArray(workbench?.timeline) ? workbench.timeline : [];
    container.dataset.runId = run.id || "";
    state.taskHistory.activeWorkbenchRunId = run.id || "";
    const chips = [
        `${t('tasks.run_status')}：${status.run_status || run.status || "-"}`,
        `${t('tasks.result_status')}：${status.result_status || "-"}`,
        `${t('tasks.attempt')}：#${Number(run.attempt || 1)}`,
        `${t('tasks.tool_events')}：${Number(status.tool_event_count || 0)}`,
        `${t('tasks.failed_tools')}：${Number(status.failed_tool_count || 0)}`,
    ];
    container.innerHTML = `
        <div class="task-workbench-head">
            <h3>${escapeHtml(task.goal || task.contract_goal || t('tasks.untitled'))}</h3>
            <div class="task-workbench-meta">
                ${chips.map((item) => `<span class="task-workbench-chip">${escapeHtml(item)}</span>`).join("")}
            </div>
            ${status.result_summary ? `<div class="task-workbench-empty">${escapeHtml(status.result_summary)}</div>` : ""}
        </div>
        ${renderWorkbenchEvidenceOverview(workbench?.evidence_overview || {
            artifacts,
            verification,
            risks,
            failures,
            audit,
            verificationClosure,
            visualVerification,
            debugAudit,
        })}
        <div class="task-workbench-grid">
            ${renderWorkbenchSection(t('tasks.audit'), renderWorkbenchAudit(audit), "full")}
            ${renderWorkbenchSection(t('tasks.workspace_snapshot'), renderWorkbenchWorkspace(workspace))}
            ${renderWorkbenchSection(t('tasks.context_evidence'), renderWorkbenchContextEvidence(contextEvidence), "full")}
            ${renderWorkbenchSection(t('tasks.context_audit'), renderWorkbenchContextAudit(contextAudit), "full")}
            ${renderWorkbenchSection(t('tasks.verification_closure'), renderWorkbenchVerificationClosure(verificationClosure), "full")}
            ${renderWorkbenchSection(t('tasks.visual_verification'), renderWorkbenchVisualVerification(visualVerification), "full")}
            ${renderWorkbenchSection(t('tasks.debug_audit'), renderWorkbenchDebugAudit(debugAudit), "full")}
            ${renderWorkbenchSection(t('tasks.context_pack'), renderWorkbenchContextPack(contextPack))}
            ${renderWorkbenchSection(t('tasks.artifacts'), renderWorkbenchArtifacts(artifacts))}
            ${renderWorkbenchSection(t('tasks.verification'), renderWorkbenchVerification(verification))}
            ${renderWorkbenchSection(t('tasks.risks'), renderWorkbenchRisks(risks))}
            ${renderWorkbenchSection(t('tasks.failures'), renderWorkbenchFailures(failures))}
            ${renderWorkbenchSection(t('tasks.completion_decisions'), renderWorkbenchCompletionDecisions(completionDecisions), "full")}
            ${renderWorkbenchSection(t('tasks.model_calls'), renderWorkbenchModelCalls(modelCalls), "full")}
            ${renderWorkbenchSection(t('tasks.plan'), renderWorkbenchPlan(plan), "full")}
            ${renderWorkbenchSection(t('tasks.timeline'), renderWorkbenchTimeline(timeline), "full")}
        </div>
    `;
    container.classList.remove("hidden");
}

function renderWorkbenchEvidenceOverview(data) {
    if (Array.isArray(data?.cards)) {
        const cards = data.cards.map((card) => renderWorkbenchEvidenceCardFromPayload(card)).join("");
        return `
            <div class="task-workbench-overview" aria-label="${escapeHtml(t('tasks.evidence_overview'))}">
                <div class="task-workbench-overview-title">${escapeHtml(t('tasks.evidence_overview'))}</div>
                <div class="task-workbench-overview-grid">${cards}</div>
            </div>
        `;
    }
    const artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
    const verification = Array.isArray(data.verification) ? data.verification : [];
    const risks = Array.isArray(data.risks) ? data.risks : [];
    const failures = Array.isArray(data.failures) ? data.failures : [];
    const auditCounts = data.audit?.counts && typeof data.audit.counts === "object" ? data.audit.counts : {};
    const closureCounts = data.verificationClosure?.counts && typeof data.verificationClosure.counts === "object"
        ? data.verificationClosure.counts
        : {};
    const closureFlags = data.verificationClosure?.flags && typeof data.verificationClosure.flags === "object"
        ? data.verificationClosure.flags
        : {};
    const closurePaths = data.verificationClosure?.artifact_paths && typeof data.verificationClosure.artifact_paths === "object"
        ? data.verificationClosure.artifact_paths
        : {};
    const visualCounts = data.visualVerification?.counts && typeof data.visualVerification.counts === "object"
        ? data.visualVerification.counts
        : {};
    const visualFlags = data.visualVerification?.flags && typeof data.visualVerification.flags === "object"
        ? data.visualVerification.flags
        : {};
    const debugCounts = data.debugAudit?.counts && typeof data.debugAudit.counts === "object" ? data.debugAudit.counts : {};
    const debugFlags = data.debugAudit?.flags && typeof data.debugAudit.flags === "object" ? data.debugAudit.flags : {};
    const finalPaths = Array.isArray(closurePaths.final) ? closurePaths.final.filter(Boolean) : [];
    const visualPaths = Array.isArray(closurePaths.visual) ? closurePaths.visual.filter(Boolean) : [];
    const finalCount = Number(closureCounts.final_artifacts || 0) || artifacts.filter((item) => String(item.role || "") === "final").length;
    const visualCount = Number(closureCounts.visual_artifacts || 0) || Number(visualCounts.visual_evidence || 0) || visualPaths.length;
    const verificationCount = Number(closureCounts.verification_records || 0) || verification.length;
    const gapCount = Number(closureCounts.gap_facts || 0);
    const debugCount = Number(debugCounts.debug_sessions || 0);
    const runtimeIssueCount = Number(debugCounts.failed_sessions || 0)
        + Number(debugCounts.timed_out_sessions || 0)
        + Number(debugCounts.runtime_error_sessions || 0)
        + failures.length;

    const cards = [
        renderWorkbenchEvidenceCard({
            title: t('tasks.evidence_deliverables'),
            tone: finalCount ? "observed" : "quiet",
            value: String(finalCount),
            facts: [
                `${t('tasks.final_artifacts')}：${finalCount}`,
                `${t('tasks.changed_paths')}：${Number(auditCounts.changed_paths || 0)}`,
                closureFlags.has_final_artifact ? t('tasks.has_final_artifact') : t('tasks.no_final_artifact'),
            ],
            paths: finalPaths.slice(0, 2).map((path) => ({ path, imagePreview: false })),
        }),
        renderWorkbenchEvidenceCard({
            title: t('tasks.evidence_visual'),
            tone: visualFlags.visual_missing ? "attention" : visualCount ? "observed" : "quiet",
            value: String(visualCount),
            facts: [
                `${t('tasks.visual_evidence')}：${visualCount}`,
                `${t('tasks.model_context_used')}：${Number(visualCounts.model_context_injected || closureCounts.model_context_artifacts || 0)}`,
                visualFlags.visual_missing ? t('tasks.visual_missing') : visualFlags.visual_observed ? t('tasks.visual_observed') : t('tasks.no_visual_evidence'),
            ],
            paths: visualPaths.slice(0, 2).map((path) => ({ path, imagePreview: true })),
        }),
        renderWorkbenchEvidenceCard({
            title: t('tasks.evidence_verification'),
            tone: gapCount ? "attention" : verificationCount ? "observed" : "quiet",
            value: String(verificationCount),
            facts: [
                `${t('tasks.verification_evidence')}：${verificationCount}`,
                `${t('tasks.sufficient_verification')}：${Number(closureCounts.sufficient_verification_records || 0)}`,
                `${t('tasks.verification_gap_facts')}：${gapCount}`,
            ],
            paths: [],
        }),
        renderWorkbenchEvidenceCard({
            title: t('tasks.evidence_runtime'),
            tone: runtimeIssueCount || debugFlags.has_runtime_errors ? "attention" : debugCount ? "observed" : "quiet",
            value: String(debugCount),
            facts: [
                `${t('tasks.debug_sessions')}：${debugCount}`,
                `${t('tasks.failures')}：${failures.length}`,
                `${t('tasks.risks')}：${risks.length}`,
                runtimeIssueCount ? t('tasks.runtime_issues_observed') : t('tasks.no_runtime_issues'),
            ],
            paths: [],
        }),
    ];
    return `
        <div class="task-workbench-overview" aria-label="${escapeHtml(t('tasks.evidence_overview'))}">
            <div class="task-workbench-overview-title">${escapeHtml(t('tasks.evidence_overview'))}</div>
            <div class="task-workbench-overview-grid">${cards.join("")}</div>
        </div>
    `;
}

function renderWorkbenchEvidenceCardFromPayload(card) {
    const id = String(card?.id || "");
    const title = card?.title_key ? t(card.title_key) : id || t('tasks.evidence_overview');
    const tone = String(card?.tone || "quiet");
    const value = String(card?.value ?? "0");
    const facts = Array.isArray(card?.facts) ? card.facts : [];
    const paths = Array.isArray(card?.paths) ? card.paths : [];
    return renderWorkbenchEvidenceCard({
        title,
        tone,
        value,
        facts: facts.map((item) => renderWorkbenchEvidenceFact(item)),
        paths: paths.map((item) => ({
            path: item?.path || "",
            imagePreview: Boolean(item?.image_preview),
        })),
    });
}

function renderWorkbenchEvidenceFact(item) {
    if (!item || typeof item !== "object") return "";
    if (item.message_key) return t(item.message_key);
    if (item.label_key) return `${t(item.label_key)}：${String(item.value ?? 0)}`;
    return String(item.text || item.message || "");
}

function renderWorkbenchEvidenceCard({ title, tone, value, facts, paths }) {
    const factRows = (facts || []).filter(Boolean).slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    const pathRows = (paths || []).map((item) => renderWorkbenchPath(item.path, { imagePreview: item.imagePreview })).join("");
    return `
        <section class="task-workbench-overview-card ${escapeHtml(tone || "quiet")}">
            <div class="task-workbench-overview-card-head">
                <strong>${escapeHtml(title)}</strong>
                <b>${escapeHtml(value)}</b>
            </div>
            <div class="task-workbench-overview-facts">${factRows}</div>
            ${pathRows ? `<div class="task-workbench-overview-paths">${pathRows}</div>` : ""}
        </section>
    `;
}

function renderWorkbenchAudit(audit) {
    if (!audit || typeof audit !== "object") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const counts = audit.counts && typeof audit.counts === "object" ? audit.counts : {};
    const verification = audit.verification && typeof audit.verification === "object" ? audit.verification : {};
    const changedPaths = Array.isArray(audit.changed_paths) ? audit.changed_paths : [];
    const failureTools = Array.isArray(audit.failure_tools) ? audit.failure_tools.filter(Boolean) : [];
    const riskCodes = Array.isArray(audit.risks) ? audit.risks.filter(Boolean) : [];
    const strengths = Array.isArray(verification.strengths) ? verification.strengths.filter(Boolean) : [];
    const modalities = Array.isArray(verification.modalities) ? verification.modalities.filter(Boolean) : [];
    const rows = [`
        <li>
            <strong>${escapeHtml(t('tasks.audit_counts'))}</strong>
            <span>${escapeHtml([
                `${t('tasks.artifacts')}：${Number(counts.artifacts || 0)}`,
                `${t('tasks.changed_paths')}：${Number(counts.changed_paths || 0)}`,
                `${t('tasks.verification')}：${Number(counts.verification || 0)}`,
                `${t('tasks.risks')}：${Number(counts.risks || 0)}`,
                `${t('tasks.failures')}：${Number(counts.failures || 0)}`,
                `${t('tasks.advisories')}：${Number(counts.runtime_advisories || 0)}`,
                `${t('tasks.visual_evidence')}：${Number(counts.visual_context || 0)}`,
            ].join(" · "))}</span>
        </li>
    `];

    if (strengths.length || modalities.length) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.verification_evidence'))}</strong>
                <span>${escapeHtml([
                    strengths.length ? `${t('tasks.verification_strengths')}：${strengths.join(" · ")}` : "",
                    modalities.length ? `${t('tasks.verification_modalities')}：${modalities.join(" · ")}` : "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    }

    changedPaths.slice(0, 10).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.changed_path'))}</strong>
                <span>${escapeHtml([item.kind, item.status, item.tool].filter(Boolean).join(" · "))}</span>
                ${renderWorkbenchPath(item.path, { imagePreview: isWorkbenchVisualRecord(item) })}
            </li>
        `);
    });

    if (failureTools.length || riskCodes.length) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.risk_evidence'))}</strong>
                <span>${escapeHtml([
                    failureTools.length ? `${t('tasks.failure_tools')}：${failureTools.slice(0, 8).join(" · ")}` : "",
                    riskCodes.length ? `${t('tasks.risks')}：${riskCodes.slice(0, 8).join(" · ")}` : "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    }

    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderWorkbenchContextEvidence(summary) {
    if (!summary || typeof summary !== "object") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const capability = summary.capability && typeof summary.capability === "object" ? summary.capability : {};
    const phases = Array.isArray(summary.context_phases) ? summary.context_phases.filter(Boolean) : [];
    const recordKinds = Array.isArray(summary.context_record_kinds) ? summary.context_record_kinds.filter(Boolean) : [];
    const visualContext = Array.isArray(summary.visual_context) ? summary.visual_context : [];
    const advisories = Array.isArray(summary.runtime_advisories) ? summary.runtime_advisories : [];
    const rows = [];

    if (Number(summary.context_pack_count || 0) || phases.length || recordKinds.length) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.context_scope'))}</strong>
                <span>${escapeHtml([
                    `${t('tasks.context_packs')}：${Number(summary.context_pack_count || 0)}`,
                    `${t('tasks.context_records')}：${Number(summary.context_record_count || 0)}`,
                    phases.length ? `${t('tasks.context_phases')}：${phases.join(" / ")}` : "",
                    recordKinds.length ? `${t('tasks.context_record_kinds')}：${recordKinds.slice(0, 10).join(" · ")}` : "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    }

    if (capability.target_capability_ids || capability.visual_verification_tool_ids) {
        const targets = Array.isArray(capability.target_capability_ids) ? capability.target_capability_ids : [];
        const visualTools = Array.isArray(capability.visual_verification_tool_ids) ? capability.visual_verification_tool_ids : [];
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.capability_facts'))}</strong>
                <span>${escapeHtml([
                    `${t('tasks.available_tools')}：${Number(capability.available_tool_count || 0)}`,
                    `${t('tasks.unavailable_tools')}：${Number(capability.unavailable_tool_count || 0)}`,
                    targets.length ? `${t('tasks.target_capabilities')}：${targets.slice(0, 8).join(" · ")}` : "",
                    visualTools.length ? `${t('tasks.visual_tools')}：${visualTools.slice(0, 8).join(" · ")}` : "",
                    Number(capability.advisory_count || 0) ? `${t('tasks.advisories')}：${Number(capability.advisory_count || 0)}` : "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    }

    visualContext.slice(0, 8).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.visual_evidence'))}</strong>
                <span>${escapeHtml([
                    item.tool || "",
                    item.source_type || "",
                    item.artifact_kind || "",
                    item.model_context_eligible || item.injected_into_model_context ? t('tasks.model_context_used') : "",
                    item.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
                    item.width && item.height ? `${item.width}x${item.height}` : "",
                ].filter(Boolean).join(" · "))}</span>
                ${renderWorkbenchPath(item.path, { imagePreview: true })}
            </li>
        `);
    });

    advisories.slice(0, 10).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(item.code || t('tasks.advisory'))}</strong>
                <span>${escapeHtml([
                    item.source || "",
                    item.tool || item.capability_id || "",
                    item.recommended_action ? `${t('tasks.recommended_action')}：${item.recommended_action}` : "",
                    item.message || "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    });

    if (!rows.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderWorkbenchContextAudit(audit) {
    if (!audit || typeof audit !== "object" || audit.kind !== "context_audit") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const counts = audit.counts && typeof audit.counts === "object" ? audit.counts : {};
    const flags = audit.flags && typeof audit.flags === "object" ? audit.flags : {};
    const phases = Array.isArray(audit.phase_summary) ? audit.phase_summary : [];
    const sourceSummary = Array.isArray(audit.source_summary) ? audit.source_summary : [];
    const trustSummary = Array.isArray(audit.trust_summary) ? audit.trust_summary : [];
    const freshnessSummary = Array.isArray(audit.freshness_summary) ? audit.freshness_summary : [];
    const historicalRecords = Array.isArray(audit.historical_records) ? audit.historical_records : [];
    const hygieneRecords = Array.isArray(audit.hygiene_records) ? audit.hygiene_records : [];
    const rows = [];

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.context_audit_boundary_title'))}</strong>
            <span>${escapeHtml(audit.boundary === "audit_only" ? t('tasks.context_audit_boundary') : audit.boundary || "")}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.context_audit_counts'))}</strong>
            <span>${escapeHtml([
                `${t('tasks.context_packs')}：${Number(counts.context_packs || 0)}`,
                `${t('tasks.context_records')}：${Number(counts.records || 0)}`,
                `${t('tasks.tokens')}：${Number(counts.token_estimate || 0)}`,
                `${t('tasks.context_current_records')}：${Number(counts.current_records || 0)}`,
                `${t('tasks.context_historical_records')}：${Number(counts.historical_records || 0)}`,
                `${t('tasks.context_memory_records')}：${Number(counts.memory_records || 0)}`,
                `${t('tasks.context_lineage_records')}：${Number(counts.task_lineage_records || 0)}`,
                `${t('tasks.context_previous_contract_records')}：${Number(counts.previous_contract_records || 0)}`,
                `${t('tasks.context_hygiene_records')}：${Number(counts.hygiene_records || 0)}`,
            ].join(" · "))}</span>
        </li>
    `);

    if (flags.has_task_id_gaps || Number(counts.different_task_records || 0)) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.context_task_identity'))}</strong>
                <span>${escapeHtml([
                    audit.run_task_id ? `${t('tasks.task_id')}：${audit.run_task_id}` : "",
                    `${t('tasks.context_task_id_gaps')}：${Number(counts.records_without_task_id || 0)}`,
                    `${t('tasks.context_different_task_records')}：${Number(counts.different_task_records || 0)}`,
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    }

    phases.slice(0, 8).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(`${t('tasks.context_phase')}：${item.phase || "-"}`)}</strong>
                <span>${escapeHtml([
                    `${t('tasks.context_packs')}：${Number(item.pack_count || 0)}`,
                    `${t('tasks.context_records')}：${Number(item.record_count || 0)}`,
                    `${t('tasks.tokens')}：${Number(item.token_estimate || 0)}`,
                    `${t('tasks.context_historical_records')}：${Number(item.historical_records || 0)}`,
                    Array.isArray(item.record_kinds) && item.record_kinds.length ? `${t('tasks.context_record_kinds')}：${item.record_kinds.slice(0, 8).join(" · ")}` : "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `);
    });

    const distributionText = [
        renderAuditCounterSummary(sourceSummary, "source_type", t('tasks.source_types')),
        renderAuditCounterSummary(trustSummary, "trust", t('tasks.trust_levels')),
        renderAuditCounterSummary(freshnessSummary, "freshness", t('tasks.freshness_levels')),
    ].filter(Boolean).join(" · ");
    if (distributionText) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.context_distribution'))}</strong>
                <span>${escapeHtml(distributionText)}</span>
            </li>
        `);
    }

    historicalRecords.slice(0, 6).forEach((item) => {
        rows.push(renderWorkbenchContextAuditRecord(t('tasks.context_historical_record'), item));
    });
    hygieneRecords.slice(0, 4).forEach((item) => {
        rows.push(renderWorkbenchContextAuditRecord(t('tasks.context_hygiene_record'), item));
    });

    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderAuditCounterSummary(items, key, title) {
    if (!items.length) return "";
    return `${title}：${items.slice(0, 4).map((item) => `${item[key] || "unknown"}(${Number(item.count || 0)})`).join(" / ")}`;
}

function renderWorkbenchContextAuditRecord(title, item) {
    return `
        <li>
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml([
                item.phase || "",
                item.kind || "",
                item.source_type || "",
                item.trust || "",
                item.freshness || "",
                item.task_id ? `${t('tasks.task_id')}：${item.task_id}` : "",
            ].filter(Boolean).join(" · "))}</span>
            ${item.content_preview ? `<code>${escapeHtml(item.content_preview)}</code>` : ""}
        </li>
    `;
}

function renderWorkbenchVerificationClosure(closure) {
    if (!closure || typeof closure !== "object" || closure.kind !== "verification_closure") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const counts = closure.counts && typeof closure.counts === "object" ? closure.counts : {};
    const flags = closure.flags && typeof closure.flags === "object" ? closure.flags : {};
    const modalities = closure.modalities && typeof closure.modalities === "object" ? closure.modalities : {};
    const paths = closure.artifact_paths && typeof closure.artifact_paths === "object" ? closure.artifact_paths : {};
    const sourceKinds = Array.isArray(closure.source_kinds) ? closure.source_kinds.filter(Boolean) : [];
    const modelFacts = Array.isArray(closure.model_facts) ? closure.model_facts.filter(Boolean) : [];
    const gapFacts = Array.isArray(closure.gap_facts) ? closure.gap_facts.filter(Boolean) : [];
    const finalPaths = Array.isArray(paths.final) ? paths.final.filter(Boolean) : [];
    const visualPaths = Array.isArray(paths.visual) ? paths.visual.filter(Boolean) : [];
    const rows = [];

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.verification_closure_boundary'))}</strong>
            <span>${escapeHtml(closure.boundary === "evidence_only" ? t('tasks.verification_closure_boundary_evidence_only') : closure.boundary || "")}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.verification_closure_counts'))}</strong>
            <span>${escapeHtml([
                `${t('tasks.verification_evidence')}：${Number(counts.verification_records || 0)}`,
                `${t('tasks.sufficient_verification')}：${Number(counts.sufficient_verification_records || 0)}`,
                `${t('tasks.fresh_verification')}：${Number(counts.fresh_verification_records || 0)}`,
                `${t('tasks.stale_verification')}：${Number(counts.stale_verification_records || 0)}`,
                `${t('tasks.final_artifacts')}：${Number(counts.final_artifacts || 0)}`,
                `${t('tasks.visual_artifacts')}：${Number(counts.visual_artifacts || 0)}`,
                `${t('tasks.log_artifacts')}：${Number(counts.log_artifacts || 0)}`,
                `${t('tasks.model_context_used')}：${Number(counts.model_context_artifacts || 0)}`,
                `${t('tasks.verification_gap_facts')}：${Number(counts.gap_facts || 0)}`,
            ].join(" · "))}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.verification_closure_facts'))}</strong>
            <span>${escapeHtml([
                flags.has_required_gap ? t('tasks.has_required_gap') : "",
                flags.has_verification_evidence ? t('tasks.has_verification_evidence') : "",
                flags.has_sufficient_verification ? t('tasks.has_sufficient_verification') : "",
                flags.has_final_artifact ? t('tasks.has_final_artifact') : "",
                flags.has_visual_evidence ? t('tasks.has_visual_evidence') : "",
                flags.visual_entered_model_context ? t('tasks.visual_entered_model_context') : "",
                flags.has_debug_evidence ? t('tasks.has_debug_evidence') : "",
                flags.verification_after_latest_change_observed ? t('tasks.fresh_verification') : "",
                flags.has_stale_verification ? t('tasks.stale_verification') : "",
                flags.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
            ].filter(Boolean).join(" · ") || t('tasks.none'))}</span>
        </li>
    `);

    const modalityText = [
        Array.isArray(modalities.required) && modalities.required.length ? `${t('tasks.required_modalities')}：${modalities.required.join(" · ")}` : "",
        Array.isArray(modalities.observed) && modalities.observed.length ? `${t('tasks.observed_modalities')}：${modalities.observed.join(" · ")}` : "",
        Array.isArray(modalities.missing) && modalities.missing.length ? `${t('tasks.missing_modalities')}：${modalities.missing.join(" · ")}` : "",
    ].filter(Boolean).join(" · ");
    if (modalityText) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.verification_modalities'))}</strong>
                <span>${escapeHtml(modalityText)}</span>
            </li>
        `);
    }

    if (sourceKinds.length) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.verification_sources'))}</strong>
                <span>${escapeHtml(sourceKinds.slice(0, 12).join(" · "))}</span>
            </li>
        `);
    }

    [...finalPaths.slice(0, 6).map((path) => [t('tasks.final_artifact'), path, false]),
     ...visualPaths.slice(0, 6).map((path) => [t('tasks.visual_artifact'), path, true])]
        .forEach(([label, path, imagePreview]) => {
            rows.push(`
                <li>
                    <strong>${escapeHtml(label)}</strong>
                    ${renderWorkbenchPath(path, { imagePreview })}
                </li>
            `);
        });

    gapFacts.slice(0, 8).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.verification_gap_fact'))}</strong>
                <span>${escapeHtml(item)}</span>
            </li>
        `);
    });

    modelFacts.slice(0, 6).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.model_fact'))}</strong>
                <span>${escapeHtml(item)}</span>
            </li>
        `);
    });

    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderWorkbenchVisualVerification(summary) {
    if (!summary || typeof summary !== "object" || summary.kind !== "visual_verification") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const counts = summary.counts && typeof summary.counts === "object" ? summary.counts : {};
    const flags = summary.flags && typeof summary.flags === "object" ? summary.flags : {};
    const modalities = summary.modalities && typeof summary.modalities === "object" ? summary.modalities : {};
    const sources = summary.sources && typeof summary.sources === "object" ? summary.sources : {};
    const records = Array.isArray(summary.records) ? summary.records : [];
    const contextRecords = Array.isArray(summary.model_context_records) ? summary.model_context_records : [];
    const debugSessions = Array.isArray(summary.debug_sessions) ? summary.debug_sessions : [];
    const rows = [];

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.visual_boundary'))}</strong>
            <span>${escapeHtml(summary.boundary === "evidence_only" ? t('tasks.visual_boundary_evidence_only') : summary.boundary || "")}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.visual_verification_counts'))}</strong>
            <span>${escapeHtml([
                `${t('tasks.visual_evidence')}：${Number(counts.visual_evidence || 0)}`,
                `${t('tasks.visual_verification_records')}：${Number(counts.visual_verification_records || 0)}`,
                `${t('tasks.debug_sessions')}：${Number(counts.debug_sessions || 0)}`,
                `${t('tasks.model_context_used')}：${Number(counts.model_context_injected || 0)}`,
                `${t('tasks.visual_runtime_errors')}：${Number(counts.runtime_error_records || 0)}`,
                `${t('tasks.console_errors')}：${Number(counts.console_errors || 0)}`,
                `${t('tasks.page_errors')}：${Number(counts.page_errors || 0)}`,
                `${t('tasks.failed_requests')}：${Number(counts.failed_requests || 0)}`,
            ].join(" · "))}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.visual_facts'))}</strong>
            <span>${escapeHtml([
                flags.visual_required ? t('tasks.visual_required') : "",
                flags.visual_observed ? t('tasks.visual_observed') : "",
                flags.visual_missing ? t('tasks.visual_missing') : "",
                flags.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
                flags.model_context_available ? t('tasks.model_context_available') : "",
                flags.model_context_injected ? t('tasks.model_context_injected') : "",
            ].filter(Boolean).join(" · ") || t('tasks.none'))}</span>
        </li>
    `);

    const modalityText = [
        Array.isArray(modalities.required) && modalities.required.length ? `${t('tasks.required_modalities')}：${modalities.required.join(" · ")}` : "",
        Array.isArray(modalities.observed) && modalities.observed.length ? `${t('tasks.observed_modalities')}：${modalities.observed.join(" · ")}` : "",
        Array.isArray(modalities.missing) && modalities.missing.length ? `${t('tasks.missing_modalities')}：${modalities.missing.join(" · ")}` : "",
    ].filter(Boolean).join(" · ");
    if (modalityText) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.visual_modalities'))}</strong>
                <span>${escapeHtml(modalityText)}</span>
            </li>
        `);
    }

    const sourceText = [
        Array.isArray(sources.tools) && sources.tools.length ? `${t('tasks.tools')}：${sources.tools.join(" · ")}` : "",
        Array.isArray(sources.source_types) && sources.source_types.length ? `${t('tasks.source_types')}：${sources.source_types.join(" · ")}` : "",
    ].filter(Boolean).join(" · ");
    if (sourceText) {
        rows.push(`
            <li>
                <strong>${escapeHtml(t('tasks.visual_sources'))}</strong>
                <span>${escapeHtml(sourceText)}</span>
            </li>
        `);
    }

    records.slice(0, 8).forEach((item) => {
        rows.push(renderWorkbenchVisualRecord(t('tasks.visual_evidence'), item));
    });
    contextRecords.slice(0, 4).forEach((item) => {
        rows.push(renderWorkbenchVisualRecord(t('tasks.model_context_record'), item));
    });
    debugSessions.slice(0, 4).forEach((item) => {
        rows.push(`
            <li>
                <strong>${escapeHtml(item.source_type || item.tool || t('tasks.debug_session'))}</strong>
                <span>${escapeHtml([
                    item.status || "",
                    item.exit_code != null ? `exit=${item.exit_code}` : "",
                    item.timed_out ? t('tasks.timed_out') : "",
                    item.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
                    item.diagnostic_count ? `${t('tasks.diagnostics')}：${Number(item.diagnostic_count || 0)}` : "",
                ].filter(Boolean).join(" · "))}</span>
                ${item.command ? `<code>${escapeHtml(item.command)}</code>` : ""}
            </li>
        `);
    });

    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderWorkbenchVisualRecord(title, item) {
    return `
        <li>
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml([
                item.tool || "",
                item.source_type || "",
                item.artifact_kind || "",
                item.format || "",
                item.width && item.height ? `${item.width}x${item.height}` : "",
                item.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
                item.injected_into_model_context ? t('tasks.model_context_injected') : "",
            ].filter(Boolean).join(" · "))}</span>
            ${renderWorkbenchPath(item.path, { imagePreview: isWorkbenchVisualRecord(item) })}
        </li>
    `;
}

function renderWorkbenchDebugAudit(audit) {
    if (!audit || typeof audit !== "object" || audit.kind !== "debug_audit") {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const counts = audit.counts && typeof audit.counts === "object" ? audit.counts : {};
    const flags = audit.flags && typeof audit.flags === "object" ? audit.flags : {};
    const records = Array.isArray(audit.records) ? audit.records : [];
    const installSessions = Array.isArray(audit.dependency_install_sessions) ? audit.dependency_install_sessions : [];
    const previewSessions = Array.isArray(audit.preview_sessions) ? audit.preview_sessions : [];
    const serviceSessions = Array.isArray(audit.service_sessions) ? audit.service_sessions : [];
    const longSessions = Array.isArray(audit.long_sessions) ? audit.long_sessions : [];
    const problemSessions = Array.isArray(audit.problem_sessions) ? audit.problem_sessions : [];
    const rows = [];

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.debug_boundary'))}</strong>
            <span>${escapeHtml(audit.boundary === "evidence_only" ? t('tasks.debug_boundary_evidence_only') : audit.boundary || "")}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.debug_audit_counts'))}</strong>
            <span>${escapeHtml([
                `${t('tasks.debug_sessions')}：${Number(counts.debug_sessions || 0)}`,
                `${t('tasks.dependency_install_sessions')}：${Number(counts.dependency_install_sessions || 0)}`,
                `${t('tasks.preview_sessions')}：${Number(counts.preview_sessions || 0)}`,
                `${t('tasks.service_sessions')}：${Number(counts.service_sessions || 0)}`,
                `${t('tasks.timed_out')}：${Number(counts.timed_out_sessions || 0)}`,
                `${t('tasks.failed_sessions')}：${Number(counts.failed_sessions || 0)}`,
                `${t('tasks.warning_sessions')}：${Number(counts.warning_sessions || 0)}`,
                `${t('tasks.runtime_errors_seen')}：${Number(counts.runtime_error_sessions || 0)}`,
                `${t('tasks.long_sessions')}：${Number(counts.long_sessions || 0)}`,
                `${t('tasks.diagnostics')}：${Number(counts.diagnostics || 0)}`,
            ].join(" · "))}</span>
        </li>
    `);

    rows.push(`
        <li>
            <strong>${escapeHtml(t('tasks.debug_facts'))}</strong>
            <span>${escapeHtml([
                flags.has_dependency_install ? t('tasks.has_dependency_install') : "",
                flags.has_preview_service ? t('tasks.has_preview_service') : "",
                flags.has_service_evidence ? t('tasks.has_service_evidence') : "",
                flags.has_port_or_process_check ? t('tasks.has_port_or_process_check') : "",
                flags.has_timeout ? t('tasks.has_timeout') : "",
                flags.has_failure ? t('tasks.has_failure') : "",
                flags.has_warning ? t('tasks.has_warning') : "",
                flags.has_runtime_errors ? t('tasks.runtime_errors_seen') : "",
                flags.has_long_session ? t('tasks.has_long_session') : "",
                flags.has_truncated_streams ? t('tasks.has_truncated_streams') : "",
            ].filter(Boolean).join(" · ") || t('tasks.none'))}</span>
        </li>
    `);

    [
        ...installSessions.slice(0, 4).map((item) => [t('tasks.dependency_install_session'), item]),
        ...previewSessions.slice(0, 4).map((item) => [t('tasks.preview_session'), item]),
        ...serviceSessions.slice(0, 3).map((item) => [t('tasks.service_session'), item]),
        ...longSessions.slice(0, 3).map((item) => [t('tasks.long_session'), item]),
        ...problemSessions.slice(0, 6).map((item) => [t('tasks.problem_session'), item]),
    ].forEach(([title, item]) => {
        rows.push(renderWorkbenchDebugRecord(title, item));
    });

    if (!installSessions.length && !previewSessions.length && !serviceSessions.length && !longSessions.length && !problemSessions.length) {
        records.slice(0, 6).forEach((item) => {
            rows.push(renderWorkbenchDebugRecord(t('tasks.debug_session'), item));
        });
    }

    return `<ul class="task-workbench-list">${rows.join("")}</ul>`;
}

function renderWorkbenchDebugRecord(title, item) {
    const duration = Number.isFinite(Number(item.duration_seconds)) && Number(item.duration_seconds) > 0
        ? `${Number(item.duration_seconds).toFixed(1)}s`
        : "";
    return `
        <li>
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml([
                item.role || "",
                item.source_type || "",
                item.status || "",
                item.exit_code != null ? `exit=${item.exit_code}` : "",
                item.timed_out ? t('tasks.timed_out') : "",
                duration,
                item.diagnostic_count ? `${t('tasks.diagnostics')}：${Number(item.diagnostic_count || 0)}` : "",
                item.stderr_chars ? `stderr=${Number(item.stderr_chars || 0)}` : "",
            ].filter(Boolean).join(" · "))}</span>
            ${item.command ? `<code>${escapeHtml(item.command)}</code>` : ""}
        </li>
    `;
}

function renderWorkbenchSection(title, body, extraClass = "") {
    return `
        <section class="task-workbench-section ${escapeHtml(extraClass)}">
            <h4>${escapeHtml(title)}</h4>
            ${body}
        </section>
    `;
}

function renderWorkbenchPath(path, options = {}) {
    const text = String(path || "").trim();
    if (!text) return "";
    const safe = escapeHtml(text);
    const runId = state.taskHistory.activeWorkbenchRunId || $("task-workbench")?.dataset.runId || "";
    const previewUrl = options.imagePreview && runId
        ? `/runs/${encodeURIComponent(runId)}/artifacts/content?path=${encodeURIComponent(text)}`
        : "";
    const safePreviewUrl = escapeHtml(previewUrl);
    return `
        <div class="task-workbench-path">
            ${previewUrl ? `<a class="task-workbench-image-preview" href="${safePreviewUrl}" target="_blank" rel="noopener"><img src="${safePreviewUrl}" alt="${escapeHtml(t('tasks.artifact_preview'))}" loading="lazy"></a>` : ""}
            <code title="${safe}">${safe}</code>
            <div class="task-workbench-path-actions">
                <button type="button" data-workbench-action="open_artifact" data-path="${safe}">${escapeHtml(t('tasks.open_artifact'))}</button>
                <button type="button" data-workbench-action="copy_path" data-path="${safe}">${escapeHtml(t('tasks.copy_path'))}</button>
            </div>
        </div>
    `;
}

function isWorkbenchVisualRecord(item) {
    const kind = String(item?.kind || item?.artifact_kind || "").toLowerCase();
    const role = String(item?.role || "").toLowerCase();
    const format = String(item?.format || "").toLowerCase();
    const path = String(item?.path || "").toLowerCase();
    return Boolean(
        role === "screenshot"
        || role === "preview"
        || ["image", "screenshot", "render", "render_image", "viewport_screenshot", "visual_capture", "pdf_page_render"].includes(kind)
        || ["png", "jpeg", "jpg", "webp", "gif", "bmp"].includes(format)
        || /\.(png|jpe?g|webp|gif|bmp)$/.test(path)
    );
}

async function handleWorkbenchPathAction(button) {
    const action = button.dataset.workbenchAction || "";
    const path = button.dataset.path || "";
    if (!path) return;
    if (action === "copy_path") {
        await navigator.clipboard.writeText(path);
        showToast(t('tasks.path_copied'));
        return;
    }
    if (action === "open_artifact") {
        const runId = $("task-workbench")?.dataset.runId || "";
        if (!runId) {
            showToast(t('tasks.run_missing'));
            return;
        }
        await runTaskHistoryAction("open_artifact", runId, button, { path });
    }
}

function renderWorkbenchArtifacts(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => {
        const size = Number.isFinite(Number(item.size)) ? ` · ${formatFileSize(Number(item.size))}` : "";
        const validation = item.validation && typeof item.validation === "object"
            ? ` · ${item.validation.valid === false ? t('tasks.invalid') : t('tasks.valid')}${item.validation.text_chars ? ` · ${t('tasks.chars', {count: Number(item.validation.text_chars)})}` : ""}`
            : "";
        return `
            <li>
                <strong>${escapeHtml([item.role, item.kind].filter(Boolean).join(" · ") || item.path || t('tasks.artifact'))}</strong>
                <span>${escapeHtml([item.status, item.tool].filter(Boolean).join(" · "))}${escapeHtml(size + validation)}</span>
                ${renderWorkbenchPath(item.path, { imagePreview: isWorkbenchVisualRecord(item) })}
            </li>
        `;
    }).join("")}</ul>`;
}

function renderWorkbenchWorkspace(snapshot) {
    if (!snapshot || !snapshot.schema_version) {
        return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    }
    const extensions = snapshot.extension_counts && typeof snapshot.extension_counts === "object"
        ? Object.entries(snapshot.extension_counts).slice(0, 8).map(([key, value]) => `${key}:${value}`).join(" · ")
        : "";
    const patterns = Array.isArray(snapshot.observed_patterns)
        ? snapshot.observed_patterns.slice(0, 6).map((item) => item.id).filter(Boolean).join(" · ")
        : "";
    return `<ul class="task-workbench-list">
        <li>
            <strong>${escapeHtml(snapshot.name || t('tasks.workspace_snapshot'))}</strong>
            <span>${escapeHtml([
                snapshot.readable ? t('tasks.readable') : t('tasks.unreadable'),
                `${t('tasks.files')}：${Number(snapshot.file_count || 0)}`,
                `${t('tasks.directories')}：${Number(snapshot.directory_count || 0)}`,
            ].filter(Boolean).join(" · "))}</span>
            ${snapshot.path ? `<code>${escapeHtml(snapshot.path)}</code>` : ""}
        </li>
        ${extensions ? `<li><strong>${escapeHtml(t('tasks.file_types'))}</strong><span>${escapeHtml(extensions)}</span></li>` : ""}
        ${patterns ? `<li><strong>${escapeHtml(t('tasks.observed_patterns'))}</strong><span>${escapeHtml(patterns)}</span></li>` : ""}
    </ul>`;
}

function renderWorkbenchContextPack(pack) {
    const ledger = pack?.ledger || {};
    const records = Array.isArray(ledger.records) ? ledger.records : [];
    if (!records.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    const phase = pack.phase || ledger.phase || "";
    return `${phase ? `<div class="task-workbench-empty">${escapeHtml(t('tasks.context_phase'))}：${escapeHtml(phase)}</div>` : ""}
    <ul class="task-workbench-list">${records.slice(0, 12).map((item) => `
        <li>
            <strong>${escapeHtml(item.kind || t('tasks.context_record'))}</strong>
            <span>${escapeHtml([
                item.source_type || "",
                item.trust || "",
                item.freshness || "",
                item.token_estimate != null ? `${Number(item.token_estimate || 0)} tokens` : "",
            ].filter(Boolean).join(" · "))}</span>
            ${item.content_preview ? `<code>${escapeHtml(item.content_preview)}</code>` : ""}
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchVerification(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => `
        <li>
            <strong>${escapeHtml(item.tool || t('tasks.verification'))}</strong>
            <span>${escapeHtml([item.status, item.strength, item.modality].filter(Boolean).join(" · "))}</span>
            ${renderWorkbenchPath(item.path)}
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchRisks(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => `
        <li>
            <strong>${escapeHtml(item.code || t('tasks.risk'))}</strong>
            <span>${escapeHtml(item.message || "")}</span>
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchFailures(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => `
        <li>
            <strong>${escapeHtml(item.tool || t('tasks.failure'))}</strong>
            ${renderWorkbenchPath(item.path)}
            <span>${escapeHtml(item.error || item.message || "")}</span>
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchCompletionDecisions(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => `
        <li>
            <strong>${escapeHtml(completionDecisionLabel(item.action))}</strong>
            <span>${escapeHtml([
                item.result_status ? `${t('tasks.result_status')}：${item.result_status}` : "",
                item.tool_call_count != null ? `${t('tasks.tool_calls')}：${Number(item.tool_call_count || 0)}` : "",
                item.content_chars != null ? `${t('tasks.chars', {count: Number(item.content_chars || 0)})}` : "",
                item.reason || "",
            ].filter(Boolean).join(" · "))}</span>
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchModelCalls(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${items.map((item) => {
        const purposeKey = `tasks.model_call_${item.purpose || "auxiliary"}`;
        const purposeLabel = t(purposeKey) === purposeKey ? (item.purpose || t('tasks.model_call_auxiliary')) : t(purposeKey);
        const elapsed = Number(item.elapsed_seconds);
        return `
            <li>
                <strong>${escapeHtml(purposeLabel)}</strong>
                <span>${escapeHtml([
                    item.status || "",
                    Number.isFinite(elapsed) ? `${elapsed.toFixed(1)}s` : "",
                    item.model || "",
                    item.provider || "",
                    item.timed_out ? t('tasks.timed_out') : "",
                    item.error || "",
                ].filter(Boolean).join(" · "))}</span>
            </li>
        `;
    }).join("")}</ul>`;
}

function completionDecisionLabel(action) {
    const labels = {
        continue_with_tools: t('tasks.decision_continue_tools'),
        final_answer_candidate: t('tasks.decision_final_answer'),
        repair_protocol: t('tasks.decision_repair_protocol'),
        no_observable_decision: t('tasks.decision_none'),
    };
    return labels[action] || action || t('tasks.decision_none');
}

function renderWorkbenchPlan(plan) {
    const steps = Array.isArray(plan?.steps) ? plan.steps : [];
    if (!steps.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    return `<ul class="task-workbench-list">${steps.map((step, index) => `
        <li>
            <strong>${escapeHtml(step.title || step.step || t('plan.step', {n: index + 1}))}</strong>
            <span>${escapeHtml([step.status || step.state, step.tool_hint].filter(Boolean).join(" · "))}</span>
        </li>
    `).join("")}</ul>`;
}

function renderWorkbenchTimeline(items) {
    if (!items.length) return `<div class="task-workbench-empty">${escapeHtml(t('tasks.none'))}</div>`;
    const visible = items.slice(-40);
    return `<ul class="task-workbench-list">${visible.map((item) => `
        <li>
            <strong>${escapeHtml([formatWorkbenchTime(item.time), item.kind, item.status].filter(Boolean).join(" · "))}</strong>
            <span>${escapeHtml(item.label || item.message || "")}</span>
            ${renderWorkbenchPath(item.path)}
        </li>
    `).join("")}</ul>`;
}

function formatWorkbenchTime(value) {
    const time = Date.parse(value || "");
    if (!Number.isFinite(time)) return "";
    return new Date(time).toLocaleString();
}

function downloadJson(filename, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || "yuntaocode-sample.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function startPreparedRun(prepared) {
    if (!prepared?.id || !prepared?.conversation_id) return;
    if (state.currentConversationId !== prepared.conversation_id) {
        await loadConversation(prepared.conversation_id);
    }
    state.pendingRunLaunch = {
        prepared_run_id: prepared.id,
        task_id: prepared.task_id || "",
    };
    $("message-input").value = prepared.goal || t('tasks.continue_goal');
    $("task-history-dialog")?.close();
    $("composer")?.requestSubmit();
}

function updateSendingState() {
    state.isSending = Boolean(
        isComposerSubmitPending()
        || isConversationStreaming()
        || latestActiveRunForConversation(state.currentConversationId)
    );
    refreshComposerState();
}

function openAuxiliaryPage(url) {
    rememberCurrentPanelState();
    if (hasActiveWork()) {
        const opened = window.open(url, "_blank", "noopener,noreferrer");
        if (opened) {
            showToast(t('toast.task_new_tab'));
        } else {
            showToast(t('toast.task_allow_popup'));
        }
        return;
    }
    window.location.href = url;
}

function openTaskHistoryDialog() {
    const dialog = $("task-history-dialog");
    const output = $("task-runbook-output");
    const workbench = $("task-workbench");
    if (output) output.classList.add("hidden");
    if (workbench) workbench.classList.add("hidden");
    refreshTaskHistory()
        .then(() => dialog?.showModal())
        .catch((error) => showToast(error.message));
}

function refreshComposerState() {
    setSendButtonState(Boolean(
        isComposerSubmitPending()
        || isConversationStreaming()
        || latestActiveRunForConversation(state.currentConversationId)
    ));
}

function syncCurrentConversationStreamStatus() {
    const statusBar = $("streaming-status-bar");
    const statusBarText = $("streaming-status-text");
    const statusBarElapsed = $("streaming-status-elapsed");
    const statusBarActions = $("status-bar-actions");
    if (!statusBar || !statusBarText || !statusBarElapsed || !statusBarActions) return;
    const activeStream = state.activeStreams.get(state.currentConversationId);
    if (!activeStream) {
        syncPersistentRunStatusBar();
        return;
    }
    const pendingAssistant = [...(activeStream.messages || [])]
        .reverse()
        .find((message) => message?.role === "assistant" && message?.metadata?.pending);
    const metadata = pendingAssistant?.metadata || {};
    const text = metadata.statusText || activeStream.message || t('status.executing');
    statusBar.classList.remove("hidden");
    statusBarText.textContent = text;
    statusBarText.title = text;
    statusBarElapsed.textContent = metadata.waitingConfirmation
        ? ""
        : formatElapsed(metadata.elapsedSeconds || 0);
    statusBarActions.classList.toggle("hidden", !metadata.waitingConfirmation);
}

function elapsedSeconds(since) {
    return Math.max(0, Math.floor((Date.now() - since) / 1000));
}

function formatElapsed(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return `${minutes}m ${rest}s`;
}

function parseTimeMs(value) {
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? parsed : 0;
}

function toolEventElapsedSeconds(item, taskProgress) {
    const progressElapsed = Number(taskProgress?.elapsed_seconds);
    const progressValue = Number.isFinite(progressElapsed) ? Math.max(0, progressElapsed) : null;
    const startedAt = Number(item?.startedAt) || parseTimeMs(taskProgress?.created_at);
    const completedAt = Number(item?.completedAt) || parseTimeMs(taskProgress?.updated_at);
    if (item?.status === "running" && startedAt) {
        return Math.max(progressValue || 0, elapsedSeconds(startedAt));
    }
    if (startedAt && completedAt && completedAt >= startedAt) {
        return Math.max(progressValue || 0, (completedAt - startedAt) / 1000);
    }
    return progressValue;
}

function formatToolElapsedChip(seconds, isRunning) {
    if (!Number.isFinite(Number(seconds))) return "";
    const value = Math.max(0, Number(seconds));
    if (!isRunning && value < 1) return t('tools.progress_elapsed_lt1');
    return t('tools.progress_elapsed', {seconds: Math.floor(value)});
}

function upsertConversationSummary(conversation) {
    if (!conversation?.id) return;
    const summary = { ...conversation };
    delete summary.messages;
    const index = state.conversations.findIndex((item) => item.id === summary.id);
    if (index >= 0) {
        state.conversations[index] = { ...state.conversations[index], ...summary };
    } else if (!state.currentWorkspaceId || summary.workspace_id === state.currentWorkspaceId) {
        state.conversations.unshift(summary);
    }
}

function formatErrorMessage(error, fallback) {
    if (!fallback) fallback = t('error.model_failed');
    if (!error) return fallback;
    if (typeof error === "string") {
        return error.trim() === "{}" ? `${fallback}：${t('error.empty_error')}` : error;
    }
    if (typeof error === "object") {
        return error.message || error.error || error.detail || JSON.stringify(error);
    }
    return String(error);
}

async function api(path, options = {}) {
    const requestHeaders = {
        ...headers(),
        ...(options.headers || {}),
    };
    if (options.body instanceof FormData) {
        delete requestHeaders["Content-Type"];
    }
    const response = await fetch(path, {
        ...options,
        headers: requestHeaders,
    });
    const raw = await response.text();
    let payload;
    try {
        payload = raw ? JSON.parse(raw) : {};
    } catch {
        payload = { success: false, error: raw || response.statusText };
    }
    if (!response.ok || !payload.success) {
        throw new Error(formatErrorMessage(payload.error || payload.message, response.statusText));
    }
    return payload.data;
}

function displayReleaseVersion(value) {
    const version = String(value || "").trim();
    if (!version) return t('updates.unknown');
    return version.toLowerCase().startsWith("v") ? version : `v${version}`;
}

function sourceUpdateSummary(data) {
    if (state.sourceUpdate.status === "checking") return t('updates.checking');
    if (!data) return state.sourceUpdate.error || t('updates.not_checked');
    if (!data.is_git_repo) return t('updates.not_git_repo');
    if (data.status === "check_failed") return t('updates.check_failed');
    if (data.status === "no_release_tags") return t('updates.no_release_tags');
    if (data.update_available && data.dirty) return t('updates.available_dirty');
    if (data.update_available) return t('updates.available');
    return t('updates.up_to_date');
}

function sourceUpdatePillText(data) {
    if (state.sourceUpdate.status === "checking") {
        return data?.current_version ? `${displayReleaseVersion(data.current_version)} · ${t('updates.checking_short')}` : t('updates.checking_short');
    }
    if (!data?.current_version) return t('updates.version');
    if (data.update_available) {
        return `${displayReleaseVersion(data.current_version)} · ${t('updates.available_short')}`;
    }
    return displayReleaseVersion(data.current_version);
}

function renderSourceUpdate() {
    const button = $("source-update-btn");
    if (!button) return;
    const data = state.sourceUpdate.data;
    button.classList.remove("hidden", "has-update", "checking", "failed");
    button.classList.toggle("has-update", Boolean(data?.update_available));
    button.classList.toggle("checking", state.sourceUpdate.status === "checking");
    button.classList.toggle("failed", state.sourceUpdate.status === "failed" || data?.status === "check_failed");
    button.textContent = sourceUpdatePillText(data);
    button.title = sourceUpdateSummary(data);
    renderSourceUpdateDialog();
}

async function loadSourceUpdate({ silent = true } = {}) {
    state.sourceUpdate.status = "checking";
    state.sourceUpdate.error = "";
    renderSourceUpdate();
    try {
        const data = await api("/updates/source");
        state.sourceUpdate = { status: "done", data, error: "" };
        if (!silent && data?.update_available) showToast(t('updates.available'));
        if (!silent && !data?.update_available) showToast(sourceUpdateSummary(data));
    } catch (error) {
        state.sourceUpdate.status = "failed";
        state.sourceUpdate.error = error.message;
        if (!silent) showToast(error.message);
    } finally {
        renderSourceUpdate();
    }
}

function sourceUpdateRows(data) {
    if (!data) return [];
    const repoLabel = data.is_git_repo
        ? `${data.branch || "HEAD"} ${data.commit ? `@ ${data.commit}` : ""}`.trim()
        : t('updates.not_git_repo');
    return [
        [t('updates.current_version'), displayReleaseVersion(data.current_version)],
        [t('updates.latest_version'), data.latest_version ? displayReleaseVersion(data.latest_version) : t('updates.unknown')],
        [t('updates.latest_source'), data.latest_source || t('updates.unknown')],
        [t('updates.repo_state'), repoLabel],
        [t('updates.local_changes'), data.dirty ? t('updates.local_dirty') : t('updates.local_clean')],
    ];
}

function renderSourceUpdateDialog() {
    const body = $("source-update-body");
    if (!body) return;
    const data = state.sourceUpdate.data;
    const statusClass = data?.update_available
        ? "has-update"
        : (state.sourceUpdate.status === "failed" || data?.status === "check_failed" ? "failed" : "");
    const rows = sourceUpdateRows(data).map(([label, value]) => `
        <dt>${escapeHtml(label)}</dt>
        <dd title="${escapeHtml(value)}">${escapeHtml(value)}</dd>
    `).join("");
    const commands = Array.isArray(data?.update_commands) ? data.update_commands : [];
    const commandText = commands.join("\n");
    const releaseLink = data?.release_url
        ? `<a href="${escapeHtml(data.release_url)}" target="_blank" rel="noopener">${escapeHtml(t('updates.open_release'))}</a>`
        : "";
    body.innerHTML = `
        <div class="source-update-status ${statusClass}">${escapeHtml(sourceUpdateSummary(data))}</div>
        ${rows ? `<dl class="source-update-grid">${rows}</dl>` : ""}
        ${releaseLink ? `<div class="hint-line">${releaseLink}</div>` : ""}
        ${commandText ? `<pre class="source-update-command">${escapeHtml(commandText)}</pre>` : `<div class="hint-line">${escapeHtml(t('updates.no_command'))}</div>`}
    `;
    const copyButton = $("copy-source-update-command-btn");
    if (copyButton) copyButton.disabled = !commandText;
}

async function copySourceUpdateCommand() {
    const commands = state.sourceUpdate.data?.update_commands || [];
    if (!commands.length) {
        showToast(t('updates.no_command'));
        return;
    }
    await navigator.clipboard.writeText(commands.join("\n"));
    showToast(t('updates.command_copied'));
}

function openSourceUpdateDialog() {
    renderSourceUpdateDialog();
    $("source-update-dialog")?.showModal();
    if (state.sourceUpdate.status === "idle") {
        loadSourceUpdate({ silent: true }).catch((error) => showToast(error.message));
    }
}

function setStatus(id, text, ok = false) {
    const el = $(id);
    el.textContent = text;
    el.style.color = ok ? "var(--success)" : "var(--danger)";
}

async function loginBackend() {
    const backendUrl = $("backend-url-input").value.trim().replace(/\/+$/, "");
    const username = $("username-input").value.trim();
    const password = $("password-input").value;
    if (!backendUrl || !username || !password) {
        setStatus("backend-state", t('auth.fill_fields'));
        return;
    }

    const data = await api("/backend/login", {
        method: "POST",
        body: JSON.stringify({ backend_url: backendUrl, username, password }),
    });
    state.backendUrl = backendUrl;
    state.backendToken = data.token || "";
    state.backendUser = username;
    localStorage.setItem("lit_backend_url", backendUrl);
    localStorage.setItem("lit_backend_token", state.backendToken);
    localStorage.setItem("lit_backend_user", username);
    $("password-input").value = "";
    renderAuthState();
    $("login-dialog").close();
    renderCurrentWorkspace();
    renderModelState();
}

function logoutBackend() {
    state.backendToken = "";
    state.backendUser = "";
    localStorage.removeItem("lit_backend_token");
    localStorage.removeItem("lit_backend_user");
    $("password-input").value = "";
    renderAuthState();
    showToast(t('toast.logged_out'));
}

async function loadAll() {
    const [workspaces, tools] = await Promise.all([
        api("/workspaces"),
        api("/tools"),
    ]);
    const [settings, plugins, backups] = await Promise.all([
        api("/settings"),
        api("/plugins"),
        api("/backups").catch(() => ({ items: [] })),
    ]);
    state.workspaces = workspaces;
    state.tools = tools;
    state.settings = settings;
    state.plugins = plugins;
    state.backups = backups?.items || [];
    renderModelOptions();
    const availableModels = getModelList().map((item) => item.id);
    if (!availableModels.includes(state.model)) {
        state.model = settings.default_model || availableModels[0] || state.model;
        localStorage.setItem("lit_model", state.model);
    }
    if ($("model-select")) $("model-select").value = state.model;
    state.accessScope = normalizeAccessScope(settings.access_scope || state.accessScope);
    state.planningPolicy = normalizePlanningPolicy(settings.planning_policy || state.planningPolicy);
    state.confirmationPolicy = normalizeConfirmationPolicy(settings.confirmation_policy || state.confirmationPolicy);
    localStorage.setItem("lit_access_scope", state.accessScope);
    localStorage.setItem("lit_planning_policy", state.planningPolicy);
    localStorage.setItem("lit_confirmation_policy", state.confirmationPolicy);
    state.pinnedWorkspaceIds = state.pinnedWorkspaceIds.filter((id) =>
        state.workspaces.some((item) => item.id === id),
    );
    savePinnedWorkspaceIds();
    if (!localStorage.getItem("lit_model") && settings.default_model) {
        state.model = settings.default_model;
        $("model-select").value = state.model;
    }

    const workspaceExists = state.workspaces.some((item) => item.id === state.currentWorkspaceId);
    if (!workspaceExists) {
        state.currentWorkspaceId = "";
        state.currentConversationId = "";
        localStorage.removeItem("lit_workspace_id");
        localStorage.removeItem("lit_conversation_id");
    }

    if (!state.currentWorkspaceId && state.workspaces.length) {
        state.currentWorkspaceId = getOrderedWorkspaces()[0].id;
        localStorage.setItem("lit_workspace_id", state.currentWorkspaceId);
    }

    renderWorkspaces();
    renderTools();
    renderPlugins();
    renderSettings();
    await refreshActiveRuns();
    await loadConversations();
    renderCurrentWorkspace();
    renderModelState();
    loadSourceUpdate({ silent: true }).catch((error) => {
        state.sourceUpdate = { status: "failed", data: state.sourceUpdate.data, error: error.message };
        renderSourceUpdate();
    });
}

function upsertWorkspace(workspace) {
    if (!workspace) return;
    workspace = { ...workspace, is_root: false };
    const index = state.workspaces.findIndex((item) => item.id === workspace.id);
    if (index >= 0) {
        state.workspaces[index] = workspace;
    } else {
        state.workspaces = [workspace, ...state.workspaces];
    }
}

async function loadConversations() {
    const workspaceExists = state.workspaces.some((item) => item.id === state.currentWorkspaceId);
    if (!state.currentWorkspaceId || !workspaceExists) {
        state.currentWorkspaceId = "";
        state.currentConversationId = "";
        localStorage.removeItem("lit_workspace_id");
        localStorage.removeItem("lit_conversation_id");
        state.conversations = [];
    } else {
        const query = new URLSearchParams({ workspace_id: state.currentWorkspaceId });
        state.conversations = await api(`/conversations?${query.toString()}`);
    }
    renderConversations();
    if (state.currentConversationId) {
        const exists = state.conversations.some((item) => item.id === state.currentConversationId);
        if (exists) {
            await loadConversation(state.currentConversationId);
        } else {
            state.currentConversationId = "";
            localStorage.removeItem("lit_conversation_id");
            renderMessages([]);
        }
    } else {
        renderMessages([]);
    }
    refreshComposerState();
    syncCurrentConversationStreamStatus();
}

function renderWorkspaces() {
    const items = getOrderedWorkspaces();
    $("workspace-list").innerHTML = items.length ? items.map((item) => {
        const pinned = isWorkspacePinned(item.id);
        const menuOpen = state.openWorkspaceMenuId === item.id;
        const workspaceRuns = activeRunsForWorkspace(item.id);
        const latestRun = workspaceRuns[0] || null;
        const subtitle = latestRun
            ? `${activeRunLabel(latestRun)} - ${formatRunUpdated(latestRun)}`
            : item.path;
        return `
        <div class="list-item workspace-item ${item.id === state.currentWorkspaceId ? "active" : ""}" data-workspace-id="${item.id}">
            <button class="workspace-main" data-workspace-select="${item.id}" title="${escapeHtml(item.path)}">
                <div class="item-title-row">
                    <div class="item-title">${pinned ? `<span class="pin-mark">${t('workspace.pinned')}</span>` : ""}${escapeHtml(item.name)}</div>
                    ${runDotMarkup(workspaceRuns)}
                </div>
                <div class="item-subtitle">${escapeHtml(subtitle)}</div>
            </button>
            <div class="workspace-menu-wrap">
                <button class="workspace-menu-button" data-workspace-menu="${item.id}" title="${t('workspace.ops')}" aria-expanded="${menuOpen ? "true" : "false"}">...</button>
                ${menuOpen ? `
                    <div class="workspace-menu">
                        <button type="button" data-workspace-pin="${item.id}">${pinned ? t('workspace.unpin') : t('workspace.pin')}</button>
                        <button type="button" data-workspace-open="${item.id}">${t('workspace.open_explorer')}</button>
                        <button type="button" class="danger-menu-item" data-workspace-remove="${item.id}">${t('workspace.remove')}</button>
                    </div>
                ` : ""}
            </div>
        </div>
    `;
    }).join("") : `<div class="item-subtitle">${t('workspace.select_dir')}</div>`;
}

function renderConversations() {
    const keyword = state.search.trim().toLowerCase();
    const items = keyword
        ? state.conversations.filter((item) => item.title.toLowerCase().includes(keyword))
        : state.conversations;

    $("conversation-list").innerHTML = items.length ? items.map((item) => {
        const activeRun = latestActiveRunForConversation(item.id);
        const running = isConversationStreaming(item.id) || Boolean(activeRun);
        const subtitle = running
            ? `${activeRunLabel(activeRun)} - ${activeRun ? formatRunUpdated(activeRun) : t('status.executing')}`
            : t('conv.messages_count', {count: item.message_count});
        return `
        <div class="conv-item ${item.id === state.currentConversationId ? "active" : ""}">
            <button class="conv-main" data-conversation-id="${item.id}">
                <div class="item-title-row">
                    <div class="item-title">${escapeHtml(item.title)}</div>
                    ${runDotMarkup(activeRun ? [activeRun] : [], running)}
                </div>
                <div class="item-subtitle">${escapeHtml(subtitle)}</div>
            </button>
            <button class="conv-delete" data-delete-conversation="${item.id}" title="${t('conv.delete_title')}">×</button>
        </div>
    `;
    }).join("") : `<div class="item-subtitle">${t('conv.no_match')}</div>`;
}

function renderTools() {
    $("tool-summary").textContent = t('tools.count', {count: state.tools.length});
}

function renderPlugins() {
    $("plugin-list").innerHTML = state.plugins.map((plugin) => `
        <div class="plugin-item">
            <div class="plugin-head">
                <div class="plugin-name">${escapeHtml(plugin.name)}</div>
                <div class="plugin-badge">${plugin.enabled ? t('plugins.enabled') : t('plugins.disabled')}</div>
            </div>
            <div class="plugin-desc">${escapeHtml(plugin.description)}</div>
            <div class="plugin-tools">
                ${plugin.tools.map((tool) => `<div>${escapeHtml(tool.name)} · ${escapeHtml(tool.id)}</div>`).join("")}
            </div>
        </div>
    `).join("");
}

function renderSettings() {
    const providers = state.settings?.providers || {};
    const volcengine = providers.volcengine || {};
    const qwen = providers.qwen || {};
    const backups = state.settings?.backups || {};
    if ($("volcengine-key-hint")) $("volcengine-key-hint").textContent = volcengine.has_api_key
        ? t('settings_js.key_configured', {hint: volcengine.api_key_hint})
        : t('settings_js.no_key');
    if ($("qwen-key-hint")) $("qwen-key-hint").textContent = qwen.has_api_key
        ? t('settings_js.key_configured', {hint: qwen.api_key_hint})
        : t('settings_js.no_key');
    if ($("backup-enabled-input")) $("backup-enabled-input").checked = backups.enabled !== false;
    if ($("backup-keep-input")) $("backup-keep-input").value = backups.keep_rounds || 50;
    if ($("access-scope-input")) $("access-scope-input").value = state.accessScope;
    if ($("planning-policy-input")) $("planning-policy-input").value = state.planningPolicy;
    if ($("confirmation-policy-input")) $("confirmation-policy-input").value = state.confirmationPolicy;
    renderBackups();
}

function renderBackups() {
    const list = $("backup-list");
    if (!list) return;
    const items = state.backups || [];
    if ($("backup-storage-hint")) $("backup-storage-hint").textContent = items.length ? t('backup.batches', {count: items.length}) : t('backup.none');
    list.innerHTML = items.length ? items.slice(0, 8).map((item, index) => `
        <div class="backup-item">
            <div class="backup-item-main">
                <strong>${index === 0 ? t('backup.latest') : t('backup.n', {n: index + 1})}</strong>
                <span>${escapeHtml(item.tool_id || "")} · ${t('backup.files', {count: Number(item.file_count || 0)})}</span>
                <em>${escapeHtml(formatBackupTime(item.created_at))}${item.restored_at ? t('backup.restored') : ""}</em>
                ${renderBackupFiles(item)}
            </div>
            <button type="button" class="secondary-button backup-restore-btn" data-restore-backup="${escapeHtml(item.id || "")}">${t('backup.restore')}</button>
        </div>
    `).join("") : `<div class="hint-line">${t('backup.hint')}</div>`;
}

function backupFileLabel(file) {
    const path = String(file?.path || "");
    if (!path) return file?.existed === false ? t('backup.new_file') : t('backup.unknown_file');
    return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function renderBackupFiles(item, limit = 5) {
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
                    <span class="backup-file-path">${escapeHtml(file.path || "")}${file.existed === false ? ` · ${t('backup.new_file')}` : ""}</span>
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

async function loadBackups() {
    const result = await api("/backups");
    state.backups = result.items || [];
    renderBackups();
}

async function restoreBackup(backupId) {
    if (!backupId) return;
    const confirmed = window.confirm(t('backup.confirm_restore'));
    if (!confirmed) return;
    const result = await api(`/backups/${encodeURIComponent(backupId)}/restore`, {
        method: "POST",
        body: JSON.stringify({}),
    });
    await loadBackups();
    showToast(t('backup.restored_n', {count: Number(result.restored_file_count || 0)}));
}

async function restoreLatestBackup() {
    const latest = state.backups?.[0];
    if (!latest?.id) {
        showToast(t('backup.no_restore'));
        return;
    }
    await restoreBackup(latest.id);
}

async function clearBackups() {
    const confirmed = window.confirm(t('backup.confirm_clear'));
    if (!confirmed) return;
    const result = await api("/backups", {
        method: "DELETE",
    });
    state.backups = result.items || [];
    renderBackups();
    showToast(t('backup.cleared'));
}

function renderCurrentWorkspace() {
    const workspace = getCurrentWorkspace();
    const workspaceRuns = workspace ? activeRunsForWorkspace(workspace.id) : [];
    const latestRun = workspaceRuns[0] || null;
    $("current-workspace-name").innerHTML = workspace
        ? `<span class="current-workspace-title">${escapeHtml(workspace.name)}</span>${runDotMarkup(workspaceRuns)}`
        : escapeHtml(t('topbar.select_project'));
    $("current-workspace-path").textContent = latestRun
        ? `${t('conv.running')} - ${activeRunLabel(latestRun)} - ${formatRunUpdated(latestRun)}`
        : (workspace ? workspace.path : t('topbar.bind_conversation'));
    $("composer-meta").textContent = workspace ? `${workspace.name} · ${getModeLabel()}` : t('composer.select_project_first');
    renderAccessScopeControl();
    renderPlanExecutionControl();
    renderConfirmationExecutionControl();
}

function renderAccessScopeControl() {
    const btn = $("access-scope-btn");
    if (!btn) return;
    const labels = {
        project_only: t('plan.access_project'),
        full_local: t('plan.access_full'),
    };
    btn.textContent = labels[state.accessScope] || labels.project_only;
    btn.setAttribute("data-access-scope", state.accessScope);
}

function cycleAccessScope() {
    const modes = ["project_only", "full_local"];
    const currentIndex = modes.indexOf(state.accessScope);
    state.accessScope = modes[(currentIndex + 1) % modes.length];
    localStorage.setItem("lit_access_scope", state.accessScope);
    renderAccessScopeControl();
    api("/settings", {
        method: "POST",
        body: JSON.stringify({ access_scope: state.accessScope }),
    }).then((settings) => {
        state.settings = settings;
        state.accessScope = normalizeAccessScope(settings.access_scope || state.accessScope);
        localStorage.setItem("lit_access_scope", state.accessScope);
        renderAccessScopeControl();
        renderSettings();
    }).catch((error) => showToast(error.message));
}

function renderPlanExecutionControl() {
    const btn = $("plan-mode-btn");
    if (!btn) return;
    const planningLabels = { off: t('plan.policy_off'), auto: t('plan.policy_auto'), always: t('plan.policy_always') };
    btn.textContent = planningLabels[state.planningPolicy] || planningLabels.auto;
    btn.classList.toggle("active", state.planningPolicy !== "off");
    btn.setAttribute("data-plan-mode", state.planningPolicy);
}

function cyclePlanExecutionMode() {
    const modes = ["auto", "always", "off"];
    const currentIndex = modes.indexOf(state.planningPolicy);
    state.planningPolicy = modes[(currentIndex + 1) % modes.length];
    localStorage.setItem("lit_planning_policy", state.planningPolicy);
    renderPlanExecutionControl();
    api("/settings", {
        method: "POST",
        body: JSON.stringify({ planning_policy: state.planningPolicy }),
    }).then((settings) => {
        state.settings = settings;
        renderSettings();
    }).catch((error) => showToast(error.message));
}

function renderConfirmationExecutionControl() {
    const btn = $("confirmation-mode-btn");
    if (!btn) return;
    const labels = {
        conservative: t('plan.exec_conservative'),
        auto: t('plan.exec_auto'),
        aggressive: t('plan.exec_aggressive'),
    };
    btn.textContent = labels[state.confirmationPolicy] || labels.auto;
    btn.setAttribute("data-confirmation-mode", state.confirmationPolicy);
}

function cycleConfirmationPolicy() {
    const modes = ["auto", "aggressive", "conservative"];
    const currentIndex = modes.indexOf(state.confirmationPolicy);
    state.confirmationPolicy = modes[(currentIndex + 1) % modes.length];
    localStorage.setItem("lit_confirmation_policy", state.confirmationPolicy);
    renderConfirmationExecutionControl();
    api("/settings", {
        method: "POST",
        body: JSON.stringify({ confirmation_policy: state.confirmationPolicy }),
    }).then((settings) => {
        state.settings = settings;
        renderSettings();
    }).catch((error) => showToast(error.message));
}

function renderModelState() {
    $("model-summary").textContent = getModeLabel();
    renderAuthState();
}

function getModelList() {
    return Array.isArray(state.settings?.models) ? state.settings.models : [];
}

function renderModelOptions() {
    const select = $("model-select");
    if (!select) return;
    const models = getModelList();
    if (!models.length) return;
    select.innerHTML = models.map((model) => `
        <option value="${escapeHtml(model.id)}">${escapeHtml(model.name || model.id)}</option>
    `).join("");
}

function renderAuthState() {
    if (state.backendToken && state.backendUser) {
        setStatus("backend-state", t('auth.logged_in', {user: state.backendUser}), true);
        $("open-login-btn")?.classList.add("hidden");
        $("logout-btn")?.classList.remove("hidden");
        return;
    }
    setStatus("backend-state", t('sidebar.not_logged_in'));
    $("open-login-btn")?.classList.remove("hidden");
    $("logout-btn")?.classList.add("hidden");
}

function getModeLabel() {
    const model = getModelList().find((item) => item.id === state.model);
    return model ? `${model.name || model.id}` : `${state.model}`;
}

function renderContextBar() {
    const battery = $("token-battery");
    if (!state.contextTokens || !state.contextLimit) {
        battery.classList.add("hidden");
        return;
    }
    battery.classList.remove("hidden");
    const pct = Math.min(Math.round((state.contextTokens / state.contextLimit) * 100), 100);
    const fill = $("battery-fill");
    fill.style.width = `${pct}%`;
    fill.classList.remove("warn", "danger");
    if (pct >= 80) fill.classList.add("danger");
    else if (pct >= 50) fill.classList.add("warn");

    const fmt = (n) => {
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
        return String(n);
    };
    const label = `${fmt(state.contextTokens)}/${fmt(state.contextLimit)}`;
    $("battery-text").textContent = label;
    battery.title = `${fmt(state.contextTokens)} / ${fmt(state.contextLimit)} tokens (${pct}%) - ${t('context.compress_click')}`;
}

async function compressContext() {
    if (!state.currentConversationId) {
        showToast(t('context.no_conversation'));
        return;
    }
    const battery = $("token-battery");
    const origTitle = battery.title;
    battery.title = t('status.compressing');
    battery.style.cursor = "wait";
    try {
        const result = await api(`/conversations/${state.currentConversationId}/compress`, {
            method: "POST",
        });
        if (result.compressed) {
            const fmt = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
            showToast(t('context.compressed', {before: fmt(result.before_tokens), after: fmt(result.after_tokens)}));
            state.contextTokens = result.after_tokens;
            state.contextLimit = result.context_limit;
            renderContextBar();
            renderCurrentWorkspace();
        } else {
            showToast(t('context.no_need'));
        }
    } catch (error) {
        showToast(t('context.compress_failed', {error: error.message}));
    } finally {
        battery.style.cursor = "pointer";
    }
}

function getCurrentWorkspace() {
    return state.workspaces.find((item) => item.id === state.currentWorkspaceId);
}

function isWorkspacePinned(workspaceId) {
    return state.pinnedWorkspaceIds.includes(workspaceId);
}

function getOrderedWorkspaces() {
    return [...state.workspaces].sort((a, b) => {
        const ap = isWorkspacePinned(a.id) ? 0 : 1;
        const bp = isWorkspacePinned(b.id) ? 0 : 1;
        if (ap !== bp) return ap - bp;
        return a.name.localeCompare(b.name, "zh-Hans-CN");
    });
}

function renderMessages(messages) {
    state.currentMessages = messages || [];
    const container = $("messages");
    const workspace = getCurrentWorkspace();
    if (!messages || !messages.length) {
        container.innerHTML = `
            <div class="empty-chat">
                <div class="empty-title">${t('chat.empty_title', {name: escapeHtml(workspace?.name || "this project")})}</div>
                <div class="prompt-suggestions">
                    <button class="suggestion" data-suggestion="${t('chat.suggestion_scan')}">${t('chat.suggestion_scan')}</button>
                    <button class="suggestion" data-suggestion="${t('chat.suggestion_login')}">${t('chat.suggestion_login')}</button>
                    <button class="suggestion" data-suggestion="${t('chat.suggestion_analyze')}">${t('chat.suggestion_analyze')}</button>
                </div>
            </div>
        `;
        return;
    }
    const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 96;
    const rendered = messages.map((message, index) => {
        const key = messageRenderKey(message, index);
        return { key, html: renderMessage(message, key) };
    });
    const children = Array.from(container.children);
    const canPatch = children.length === rendered.length
        && children.every((child, index) => child.dataset.messageKey === rendered[index].key);

    if (!canPatch) {
        container.innerHTML = rendered.map((item) => item.html).join("");
        Array.from(container.children).forEach((child, index) => {
            child.__renderHtml = rendered[index]?.html || "";
        });
    } else {
        rendered.forEach((item, index) => {
            const child = container.children[index];
            if (!child || child.__renderHtml === item.html) return;
            const template = document.createElement("template");
            template.innerHTML = item.html.trim();
            const next = template.content.firstElementChild;
            if (!next) return;
            next.__renderHtml = item.html;
            child.replaceWith(next);
        });
    }
    if (wasNearBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

function messageRenderKey(message, index) {
    const metadata = message.metadata || {};
    return [
        message.role || "message",
        metadata.guidance ? "guidance" : "message",
        index,
    ].join(":");
}

function renderMessage(message, key = "") {
    const keyAttr = key ? ` data-message-key="${escapeHtml(key)}"` : "";
    if (message.metadata?.guidance) {
        return `
            <div class="message guidance ${message.metadata?.pending ? "pending" : ""}"${keyAttr}>
                <div class="message-bubble">
                    <div class="message-chip">${t('chat.guidance_chip')}</div>
                    ${message.content ? `<div class="message-content">${formatMessageContent(message.content)}</div>` : ""}
                </div>
            </div>
        `;
    }
    return `
        <div class="message ${message.role} ${message.metadata?.pending ? "pending" : ""} ${message.metadata?.guidance ? "guidance" : ""}"${keyAttr}>
            <div class="message-bubble">
                ${renderExecutionPlan(message)}
                ${renderLiveStatus(message)}
                ${renderReasoning(message)}
                ${renderProcessHistory(message)}
                ${renderToolEvents(message)}
                ${renderExecutionNotice(message)}
                ${renderChangeSummary(message)}
                ${renderMessageAttachments(message)}
                ${message.content ? `<div class="message-content">${formatMessageContent(message.content)}</div>` : ""}
            </div>
        </div>
    `;
}

function toggleWorkspacePin(workspaceId) {
    if (isWorkspacePinned(workspaceId)) {
        state.pinnedWorkspaceIds = state.pinnedWorkspaceIds.filter((item) => item !== workspaceId);
    } else {
        state.pinnedWorkspaceIds = [workspaceId, ...state.pinnedWorkspaceIds];
    }
    state.openWorkspaceMenuId = "";
    savePinnedWorkspaceIds();
    renderWorkspaces();
}

async function openWorkspaceInExplorer(workspaceId) {
    await api(`/workspaces/${encodeURIComponent(workspaceId)}/open`, {
        method: "POST",
        body: JSON.stringify({}),
    });
    state.openWorkspaceMenuId = "";
    renderWorkspaces();
    showToast(t('workspace.opened'));
}

async function pickWorkspace() {
    const workspace = await api("/workspaces/pick", {
        method: "POST",
        body: JSON.stringify({}),
    });
    if (!workspace) return;
    upsertWorkspace(workspace);
    state.currentWorkspaceId = workspace.id;
    state.currentConversationId = "";
    localStorage.setItem("lit_workspace_id", workspace.id);
    localStorage.removeItem("lit_conversation_id");
    renderWorkspaces();
    renderCurrentWorkspace();
    renderMessages([]);
    try {
        await loadConversations();
        await loadAll();
    } catch (error) {
        showToast(t('workspace.picked_but_failed', {error: error.message}));
    }
}

async function removeWorkspace(workspaceId) {
    const workspace = state.workspaces.find((item) => item.id === workspaceId);
    if (!workspace) return;
    const confirmed = window.confirm(t('workspace.confirm_remove', {name: workspace.name}));
    if (!confirmed) return;
    await api(`/workspaces/${encodeURIComponent(workspaceId)}`, {
        method: "DELETE",
    });
    if (state.currentWorkspaceId === workspaceId) {
        state.currentWorkspaceId = "";
        state.currentConversationId = "";
        localStorage.removeItem("lit_workspace_id");
        localStorage.removeItem("lit_conversation_id");
    }
    await loadAll();
}

async function newConversation() {
    if (!state.currentWorkspaceId) {
        showToast(t('workspace.select_first'));
        return;
    }
    // 校验工作区是否仍然存在。
    const workspace = state.workspaces.find((w) => w.id === state.currentWorkspaceId);
    if (!workspace) {
        state.currentWorkspaceId = "";
        state.currentConversationId = "";
        localStorage.removeItem("lit_workspace_id");
        localStorage.removeItem("lit_conversation_id");
        showToast(t('workspace.not_found'));
        return;
    }
    try {
        const conversation = await api("/conversations", {
            method: "POST",
            body: JSON.stringify({ workspace_id: state.currentWorkspaceId }),
        });
        state.currentConversationId = conversation.id;
        const pendingWorkspaceSubmitKey = composerSubmitKey("");
        if (state.pendingComposerSubmits.delete(pendingWorkspaceSubmitKey)) {
            state.pendingComposerSubmits.add(composerSubmitKey(conversation.id));
        }
        state.contextTokens = 0;
        state.contextLimit = 0;
        localStorage.setItem("lit_conversation_id", conversation.id);
        await loadConversations();
        renderMessages(conversation.messages);
        renderContextBar();
        renderCurrentWorkspace();
        refreshComposerState();
        syncCurrentConversationStreamStatus();
        $("message-input").focus();
    } catch (error) {
        showToast(error.message || t('conv.create_failed'));
    }
}

async function loadConversation(conversationId) {
    try {
        const conversation = await api(`/conversations/${conversationId}`);
        state.currentConversationId = conversation.id;
        state.contextTokens = conversation.context_tokens || 0;
        state.contextLimit = conversation.context_limit || 0;
        localStorage.setItem("lit_conversation_id", conversation.id);
        renderContextBar();
        renderCurrentWorkspace();
        const activeStream = state.activeStreams.get(conversation.id);
        renderMessages(activeStream?.messages || withPersistentRunPlaceholder(conversation));
        renderConversations();
        refreshComposerState();
        syncCurrentConversationStreamStatus();
        syncPendingConfirmationBar();
    } catch (error) {
        showToast(error.message || t('error.load_failed'));
        console.error("loadConversation failed:", error);
    }
}

function hasPersistentRunPlaceholder(conversationId) {
    const run = latestActiveRunForConversation(conversationId);
    if (!run) return false;
    return state.currentMessages.some((message) =>
        message?.metadata?.persistentRun === true
        && message?.metadata?.runId === run.id
    );
}

function withPersistentRunPlaceholder(conversation) {
    const conversationId = conversation?.id || state.currentConversationId;
    const messages = Array.isArray(conversation?.messages)
        ? conversation.messages.map((message) => ({ ...message, metadata: { ...(message.metadata || {}) } }))
        : [];
    const run = latestActiveRunForConversation(conversationId);
    if (!run || state.activeStreams.has(conversationId)) {
        return messages;
    }

    const runContent = String(run.user_content || "").trim();
    if (runContent && !messages.some((message) =>
        message?.role === "user" && String(message.content || "").trim() === runContent
    )) {
        messages.push({
            role: "user",
            content: runContent,
            metadata: { recoveredFromActiveRun: true, runId: run.id },
        });
    }

    const hasAssistantForRun = messages.some((message) =>
        message?.role === "assistant"
        && (message?.metadata?.run_id === run.id || message?.metadata?.runId === run.id)
    );
    if (!hasAssistantForRun) {
        const createdAt = Date.parse(run.created_at || "");
        const startedAt = Number.isFinite(createdAt) ? createdAt : Date.now();
        messages.push({
            role: "assistant",
            content: "",
            metadata: {
                pending: true,
                persistentRun: true,
                runId: run.id,
                statusText: activeRunLabel(run),
                baseStatusText: activeRunLabel(run),
                startedAt,
                elapsedSeconds: elapsedSeconds(startedAt),
            },
        });
    }
    return messages;
}

async function deleteConversation(conversationId) {
    try {
        await api(`/conversations/${conversationId}`, { method: "DELETE" });
    } catch (error) {
        showToast(t('conv.delete_failed', {error: error.message}));
        return;
    }
    if (state.currentConversationId === conversationId) {
        state.currentConversationId = "";
        state.contextTokens = 0;
        state.contextLimit = 0;
        localStorage.removeItem("lit_conversation_id");
        renderMessages([]);
        renderContextBar();
        renderCurrentWorkspace();
        refreshComposerState();
        syncCurrentConversationStreamStatus();
    }
    await loadConversations();
    showToast(t('conv.deleted'));
}

async function sendGuidance(conversationId, content) {
    if (!conversationId || !content.trim()) return;
    const localMessage = {
        role: "user",
        content: content.trim(),
        created_at: new Date().toISOString(),
        metadata: { guidance: true, during_run: true, pending: true },
    };
    insertGuidanceMessage(conversationId, localMessage);
    const data = await api(`/conversations/${conversationId}/guidance`, {
        method: "POST",
        body: JSON.stringify({ content: content.trim() }),
    });
    if (data?.message) {
        localMessage.created_at = data.message.created_at || localMessage.created_at;
        localMessage.metadata = { ...(data.message.metadata || {}), guidance: true, during_run: true };
    } else {
        localMessage.metadata.pending = false;
    }
    insertGuidanceMessage(conversationId, localMessage, true);
    showToast(t('chat.guidance_sent'));
}

function insertGuidanceMessage(conversationId, message, refreshOnly = false) {
    const activeStream = state.activeStreams.get(conversationId);
    if (activeStream?.messages) {
        if (!refreshOnly) {
            let insertAt = -1;
            for (let index = activeStream.messages.length - 1; index >= 0; index -= 1) {
                const item = activeStream.messages[index];
                if (item.role === "assistant" && item.metadata?.pending) {
                    insertAt = index;
                    break;
                }
            }
            if (insertAt >= 0) {
                activeStream.messages.splice(insertAt + 1, 0, message);
            } else {
                activeStream.messages.push(message);
            }
        }
        activeStream.guidanceVersion = (activeStream.guidanceVersion || 0) + 1;
        if (state.currentMessages !== activeStream.messages) {
            state.currentMessages = activeStream.messages;
        }
    } else if (!refreshOnly) {
        state.currentMessages = [...state.currentMessages, message];
    }
    if (state.currentConversationId === conversationId) {
        const messages = activeStream?.messages || state.currentMessages;
        renderMessages(messages);
    }
}

function mergeStreamGuidanceMessages(conversationId, streamingMessages) {
    const activeStream = state.activeStreams.get(conversationId);
    if (!activeStream?.messages || activeStream.messages === streamingMessages) return;
    const guidanceMessages = activeStream.messages.filter((item) => item.metadata?.guidance && item.metadata?.during_run);
    for (const message of guidanceMessages) {
        if (streamingMessages.includes(message)) continue;
        let insertAt = -1;
        for (let index = streamingMessages.length - 1; index >= 0; index -= 1) {
            const item = streamingMessages[index];
            if (item.role === "assistant" && item.metadata?.pending) {
                insertAt = index;
                break;
            }
        }
        if (insertAt >= 0) {
            streamingMessages.splice(insertAt + 1, 0, message);
        } else {
            streamingMessages.push(message);
        }
    }
    activeStream.messages = streamingMessages;
}

function mergeFinalStreamMetadata(finalMessages, streamingAssistant) {
    if (!Array.isArray(finalMessages) || !streamingAssistant?.metadata) return finalMessages || [];
    const assistantIndex = [...finalMessages].map((message, index) => ({ message, index }))
        .reverse()
        .find((item) => item.message?.role === "assistant")?.index;
    if (assistantIndex === undefined) return finalMessages;
    const liveMetadata = streamingAssistant.metadata || {};
    const merged = finalMessages.map((message) => ({
        ...message,
        metadata: { ...(message.metadata || {}) },
    }));
    for (const key of [
        "reasoning",
        "reasoning_history",
        "response_revisions",
        "guidance_events",
        "tool_events",
        "execution_plan",
        "change_summary",
    ]) {
        if (liveMetadata[key] && !merged[assistantIndex].metadata[key]) {
            merged[assistantIndex].metadata[key] = liveMetadata[key];
        }
    }
    return merged;
}

async function sendMessage(event) {
    event.preventDefault();
    const input = $("message-input");
    const content = input.value.trim();
    const activeConversationId = state.currentConversationId;
    const activeRun = activeConversationId ? latestActiveRunForConversation(activeConversationId) : null;
    if (activeConversationId && (isConversationStreaming(activeConversationId) || activeRun)) {
        if (!content) return;
        await sendGuidance(activeConversationId, content);
        input.value = "";
        refreshComposerState();
        return;
    }
    if (!content && !state.pendingAttachments.length) return;
    const initialSubmitKey = composerSubmitKey(activeConversationId);
    if (state.pendingComposerSubmits.has(initialSubmitKey)) {
        console.debug("[YuntaoCode] duplicate composer submit suppressed");
        return;
    }
    state.pendingComposerSubmits.add(initialSubmitKey);
    updateSendingState();
    setSendButtonState(true);
    try {
        if (!state.currentConversationId) {
            await newConversation();
        }
    } catch (error) {
        state.pendingComposerSubmits.delete(initialSubmitKey);
        updateSendingState();
        throw error;
    }
    if (!state.currentConversationId) {
        state.pendingComposerSubmits.delete(initialSubmitKey);
        updateSendingState();
        return;
    }
    const conversationId = state.currentConversationId;
    const conversationSubmitKey = composerSubmitKey(conversationId);
    state.pendingComposerSubmits.delete(initialSubmitKey);
    state.pendingComposerSubmits.add(conversationSubmitKey);
    const runLaunch = state.pendingRunLaunch;
    const workspaceId = state.currentWorkspaceId;
    const previousMessages = [...state.currentMessages];
    const attachmentFiles = state.pendingAttachments.map((item) => item.file);
    const requestId = `stream-${Date.now()}-${++state.submitSeq}`;
    let uploadedAttachments = [];
    try {
        uploadedAttachments = await uploadAttachmentFiles(
            conversationId,
            workspaceId,
            attachmentFiles,
        );
    } catch (error) {
        state.pendingComposerSubmits.delete(conversationSubmitKey);
        updateSendingState();
        showToast(error.message);
        return;
    }
    if (state.currentConversationId === conversationId) {
        input.value = "";
        clearAttachmentUpload();
    }
    const streamingMessages = [
        ...previousMessages,
        {
            role: "user",
            content: content || t('attachment.placeholder'),
            metadata: { attachments: uploadedAttachments },
        },
        {
            role: "assistant",
            content: "",
            metadata: {
                pending: true,
                requestId,
                statusText: t('status.thinking'),
                baseStatusText: t('status.thinking'),
                startedAt: Date.now(),
                lastEventAt: Date.now(),
                lastProgressAt: Date.now(),
                lastHeartbeatAt: 0,
                consecutiveToolFailures: 0,
                elapsedSeconds: 0,
            },
        },
    ];
    const assistantIndex = streamingMessages.length - 1;
    streamingMessages[assistantIndex].metadata.baseStatusText = streamingMessages[assistantIndex].metadata.statusText || t('status.thinking');
    let assistantStarted = false;
    let finished = false;
    let progressTimer = null;
    let lastProgressRenderAt = 0;
    let renderScheduled = false;
    const touchProgress = (statusText = "") => {
        const metadata = streamingMessages[assistantIndex].metadata || {};
        metadata.pending = true;
        metadata.lastEventAt = Date.now();
        metadata.lastProgressAt = metadata.lastEventAt;
        metadata.waitingConfirmation = false;
        if (statusText) {
            metadata.baseStatusText = statusText;
            metadata.statusText = statusText;
        }
        streamingMessages[assistantIndex].metadata = metadata;
    };
    const renderStreamMessages = (immediate = false) => {
        mergeStreamGuidanceMessages(conversationId, streamingMessages);
        const activeStream = state.activeStreams.get(conversationId);
        if (activeStream) {
            activeStream.messages = streamingMessages;
        }
        if (state.currentConversationId !== conversationId) return;
        if (immediate) {
            renderScheduled = false;
            renderMessages(streamingMessages);
            return;
        }
        if (renderScheduled) return;
        renderScheduled = true;
        window.requestAnimationFrame(() => {
            renderScheduled = false;
            if (state.currentConversationId === conversationId) {
                renderMessages(streamingMessages);
            }
        });
    };
    const updateActiveStreamState = (status = "running", stage = "streaming", message = "") => {
        const activeStream = state.activeStreams.get(conversationId);
        if (!activeStream) return;
        activeStream.status = status;
        activeStream.stage = stage;
        activeStream.message = message || activeStream.message || t('status.executing');
        activeStream.updatedAt = new Date().toISOString();
        renderWorkspaces();
        renderConversations();
        renderCurrentWorkspace();
    };
    renderStreamMessages(true);

    const statusBar = $("streaming-status-bar");
    const statusBarText = $("streaming-status-text");
    const statusBarElapsed = $("streaming-status-elapsed");
    const statusBarActions = $("status-bar-actions");
    let confirmResolve = null;

    function showStatusBar(text) {
        if (state.currentConversationId !== conversationId) return;
        statusBar.classList.remove("hidden");
        statusBarText.textContent = text || t('status.executing');
        statusBarText.title = text || t('status.executing');
    }
    function hideStatusBar() {
        if (state.currentConversationId !== conversationId) return;
        statusBar.classList.add("hidden");
        statusBarActions.classList.add("hidden");
    }
    function setStatusBarElapsed(text) {
        if (state.currentConversationId === conversationId) {
            statusBarElapsed.textContent = text;
        }
    }
    function showConfirmUI(message) {
        if (state.currentConversationId !== conversationId) return;
        showStatusBar(message || t('status.confirm_pause'));
        setStatusBarElapsed("");
        statusBarActions.classList.remove("hidden");
    }

    showStatusBar(t('status.thinking'));
    setStatusBarElapsed(formatElapsed(0));

    const abortController = new AbortController();
    state.activeStreams.set(conversationId, {
        abortController,
        messages: streamingMessages,
        workspaceId,
        status: "running",
        stage: "streaming",
        message: t('status.thinking'),
        updatedAt: new Date().toISOString(),
    });
    state.abortController = abortController;
    state.pendingComposerSubmits.delete(conversationSubmitKey);
    updateSendingState();
    renderConversations();
    renderWorkspaces();
    renderCurrentWorkspace();
    progressTimer = setInterval(() => {
        if (finished) return;
        const metadata = streamingMessages[assistantIndex].metadata || {};
        if (!metadata.pending) return;
        const now = Date.now();
        metadata.elapsedSeconds = elapsedSeconds(metadata.startedAt || Date.now());
        metadata.silentSeconds = elapsedSeconds(metadata.lastProgressAt || metadata.lastEventAt || Date.now());
        const baseStatusText = metadata.baseStatusText || metadata.statusText || t('status.executing');
        if (metadata.waitingConfirmation) {
            metadata.statusText = baseStatusText;
            setStatusBarElapsed("");
        } else if ((metadata.routeAttemptCount || metadata.consecutiveToolFailures || 0) >= 2) {
            metadata.statusText = t('status.repeated_tool_failures', {
                tool: metadata.lastFailedTool || t('status.unknown_tool'),
                count: metadata.routeAttemptCount || metadata.consecutiveToolFailures,
            });
        } else if (metadata.silentSeconds >= 15) {
            const waitingPhases = [
                t('status.waiting_phase_response'),
                t('status.waiting_phase_connection'),
                t('status.waiting_phase_no_output'),
            ];
            const waitingPhase = waitingPhases[Math.floor(metadata.elapsedSeconds / 5) % waitingPhases.length];
            const aliveText = metadata.lastHeartbeatAt ? t('status.connection_alive') : t('status.waiting_update');
            metadata.statusText = `${baseStatusText} - ${aliveText} - ${waitingPhase} - ${t('status.no_progress_for', {time: formatElapsed(metadata.silentSeconds)})}`;
        } else {
            metadata.statusText = baseStatusText;
        }
        if (!metadata.waitingConfirmation) {
            setStatusBarElapsed(formatElapsed(metadata.elapsedSeconds));
        }
        showStatusBar(metadata.statusText);
        streamingMessages[assistantIndex].metadata = metadata;
        lastProgressRenderAt = now;
        renderStreamMessages();
    }, 1000);

    try {
        const body = {
            content,
            model: state.model,
            access_scope: state.accessScope,
            planning_policy: state.planningPolicy,
            confirmation_policy: state.confirmationPolicy,
            request_id: requestId,
        };
        if (runLaunch?.prepared_run_id) {
            body.prepared_run_id = runLaunch.prepared_run_id;
            body.task_id = runLaunch.task_id || "";
            state.pendingRunLaunch = null;
        }
        if (uploadedAttachments.length) {
            body.attachment_ids = uploadedAttachments.map((item) => item.id);
        }
        await streamApi(
            `/conversations/${conversationId}/messages/stream`,
            body,
            (eventData) => {
                if (state.activeStreams.get(conversationId)?.locallyStopped) {
                    return;
                }
                if (eventData.event === "error") {
                    if (eventData.terminal === false || eventData.recoverable === true) {
                        const metadata = streamingMessages[assistantIndex].metadata || {};
                        const message = formatErrorMessage(eventData.error, t('error.model_failed'));
                        metadata.pending = true;
                        metadata.modelProviderError = message;
                        metadata.statusText = message;
                        touchProgress(message);
                        updateActiveStreamState("running", "model_error", message);
                        showStatusBar(message);
                        streamingMessages[assistantIndex].metadata = metadata;
                        renderStreamMessages();
                        return;
                    }
                    throw new Error(formatErrorMessage(eventData.error, t('error.model_failed')));
                }
                if (eventData.event === "status") {
                    const currentMetadata = streamingMessages[assistantIndex].metadata || {};
                    if (eventData.status === "thinking") {
                        currentMetadata.pending = true;
                        currentMetadata.lastHeartbeatAt = Date.now();
                        currentMetadata.connectionAlive = true;
                        streamingMessages[assistantIndex].metadata = currentMetadata;
                        updateActiveStreamState("running", "thinking", currentMetadata.statusText || currentMetadata.baseStatusText || t('status.thinking'));
                        showStatusBar(currentMetadata.statusText || currentMetadata.baseStatusText || t('status.thinking'));
                        return;
                    }
                    touchProgress(eventData.message || t('status.thinking'));
                    updateActiveStreamState("running", eventData.status || "status", eventData.message || t('status.thinking'));
                    showStatusBar(eventData.message || t('status.thinking'));
                    if (
                        eventData.status === "repeated_route_observed"
                        || eventData.status === "repeated_route_budget_observed"
                        || eventData.status === "repeated_tool_failure"
                    ) {
                        currentMetadata.executionConvergence = eventData.execution_convergence || eventData.convergence || null;
                        currentMetadata.routeAttemptCount = eventData.route_attempt_count || 0;
                        currentMetadata.lastFailedTool = eventData.tool || currentMetadata.lastFailedTool || "";
                    }
                    streamingMessages[assistantIndex].metadata = {
                        ...currentMetadata,
                        pending: true,
                        statusText: eventData.message || t('status.thinking'),
                    };
                    renderStreamMessages();
                }
                if (eventData.event === "guidance") {
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    const guidanceEvents = metadata.guidance_events || [];
                    guidanceEvents.push({ message: eventData.message || "", time: Date.now() });
                    metadata.guidance_events = guidanceEvents;
                    metadata.pending = true;
                    metadata.statusText = t('status.guidance_received');
                    streamingMessages[assistantIndex].metadata = metadata;
                    touchProgress(metadata.statusText);
                    updateActiveStreamState("running", "guidance", metadata.statusText);
                    showStatusBar(metadata.statusText);
                    renderStreamMessages();
                }
                if (eventData.event === "heartbeat") {
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    metadata.pending = true;
                    metadata.lastHeartbeatAt = Date.now();
                    metadata.connectionAlive = eventData.connection_alive !== false;
                    metadata.heartbeatPhase = eventData.phase || "";
                    metadata.modelIdleSeconds = eventData.idle_seconds || 0;
                    if (eventData.progress && (eventData.task_id || eventData.tool)) {
                        const toolEvents = metadata.tool_events || [];
                        const toolIndex = findToolEventIndex(toolEvents, eventData);
                        if (toolIndex >= 0) {
                            toolEvents[toolIndex] = {
                                ...toolEvents[toolIndex],
                                progress: eventData.progress,
                            };
                            metadata.tool_events = toolEvents;
                        }
                    }
                    streamingMessages[assistantIndex].metadata = metadata;
                    updateActiveStreamState("running", "heartbeat", metadata.statusText || metadata.baseStatusText || t('status.model_still_processing'));
                    if (Date.now() - lastProgressRenderAt >= 5000) {
                        lastProgressRenderAt = Date.now();
                        renderStreamMessages();
                    }
                }
                if (eventData.event === "request_budget") {
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    const budget = eventData.budget || {};
                    metadata.request_budget = budget;
                    metadata.pending = true;
                    if (budget.context_limit && state.currentConversationId === conversationId) {
                        state.contextLimit = Number(budget.context_limit || 0);
                        renderContextBar();
                        renderCurrentWorkspace();
                    }
                    if (budget.tools_pruned) {
                        const budgetText = t('status.request_budget_adjusted', {
                            count: budget.tools_pruned,
                            limit: budget.context_limit || "",
                        });
                        metadata.statusText = budgetText;
                        touchProgress(budgetText);
                        updateActiveStreamState("running", "request_budget", budgetText);
                        showStatusBar(budgetText);
                    }
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "run") {
                    const run = eventData.run || {};
                    const activeStream = state.activeStreams.get(conversationId);
                    if (activeStream && run.id) {
                        activeStream.runId = run.id;
                        activeStream.workspaceId = run.workspace_id || activeStream.workspaceId || workspaceId;
                        activeStream.status = run.status || activeStream.status || "running";
                        activeStream.stage = run.stage || activeStream.stage || "created";
                        activeStream.message = run.message || activeStream.message || t('status.executing');
                        activeStream.updatedAt = run.updated_at || new Date().toISOString();
                    }
                    if (run.id) {
                        const existingIndex = state.activeRuns.findIndex((item) => item.id === run.id);
                        if (existingIndex >= 0) {
                            state.activeRuns[existingIndex] = { ...state.activeRuns[existingIndex], ...run };
                        } else {
                            state.activeRuns.push(run);
                        }
                    }
                    renderWorkspaces();
                    renderConversations();
                    renderCurrentWorkspace();
                    refreshComposerState();
                }
                if (eventData.event === "reasoning") {
                    touchProgress(t('status.reasoning'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    metadata.reasoning = `${metadata.reasoning || ""}${eventData.reasoning || ""}`;
                    metadata.pending = true;
                    metadata.statusText = t('status.reasoning');
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "tool_log") {
                    const logMessage = eventData.message || "";
                    if (logMessage) {
                        touchProgress(logMessage);
                        updateActiveStreamState("running", "tool_log", logMessage);
                        showStatusBar(logMessage);
                    }
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    const toolEvents = metadata.tool_events || [];
                    const toolIndex = findToolEventIndex(toolEvents, eventData);
                    if (toolIndex >= 0) {
                        const current = toolEvents[toolIndex];
                        const logs = [...(current.logs || []), {
                            level: eventData.level || "info",
                            message: logMessage,
                            data: eventData.data || {},
                        }].slice(-120);
                        toolEvents[toolIndex] = {
                            ...current,
                            logs,
                            progress: eventData.progress || current.progress || null,
                        };
                    }
                    metadata.tool_events = toolEvents;
                    metadata.pending = true;
                    if (logMessage) metadata.statusText = logMessage;
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "tool") {
                    const toolName = eventData.name || eventData.tool;
                    const toolLabel = eventData.status === "running"
                        ? t('tools.calling', {name: toolName})
                        : eventData.status === "failure"
                            ? t('tools.failed', {name: toolName})
                            : t('tools.completed', {name: toolName});
                    touchProgress(toolLabel);
                    updateActiveStreamState("running", "tool", toolLabel);
                    showStatusBar(toolLabel);
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    if (eventData.status === "failure") {
                        const failureSignature = JSON.stringify([
                            eventData.tool || toolName,
                            eventData.error || "",
                            eventData.input || {},
                        ]);
                        metadata.consecutiveToolFailures = metadata.lastFailureSignature === failureSignature
                            ? (metadata.consecutiveToolFailures || 0) + 1
                            : 1;
                        metadata.lastFailureSignature = failureSignature;
                        metadata.lastFailedTool = eventData.tool || toolName;
                        metadata.lastFailureError = eventData.error || "";
                    } else if (eventData.status === "success") {
                        metadata.consecutiveToolFailures = 0;
                        metadata.routeAttemptCount = 0;
                        metadata.executionConvergence = null;
                        metadata.lastFailureSignature = "";
                        metadata.lastFailedTool = "";
                        metadata.lastFailureError = "";
                    }
                    if (eventData.status === "running") {
                        metadata.strategyChangeRequired = false;
                        metadata.strategyChangeText = "";
                    }
                    const toolEvents = metadata.tool_events || [];
                    const existIdx = findToolEventIndex(toolEvents, eventData);
                    const previousToolEntry = existIdx >= 0 ? toolEvents[existIdx] : {};
                    const nowMs = Date.now();
                    const startedAt = eventData.status === "running"
                        ? (previousToolEntry.startedAt || nowMs)
                        : (previousToolEntry.startedAt || nowMs);
                    const completedAt = ["success", "failure", "partial"].includes(eventData.status)
                        ? (previousToolEntry.completedAt || nowMs)
                        : (previousToolEntry.completedAt || null);
                    const toolEntry = {
                        status: eventData.status,
                        tool: eventData.tool,
                        name: eventData.name || eventData.tool,
                        input: eventData.input || {},
                        task_id: eventData.task_id || "",
                        error: eventData.error || "",
                        output: eventData.output || null,
                        progress: eventData.progress || (existIdx >= 0 ? toolEvents[existIdx].progress || null : null),
                        logs: existIdx >= 0 ? (toolEvents[existIdx].logs || []) : [],
                        startedAt,
                        completedAt,
                    };
                    if (existIdx >= 0) {
                        toolEvents[existIdx] = { ...toolEvents[existIdx], ...toolEntry };
                    } else {
                        toolEvents.push(toolEntry);
                    }
                    metadata.tool_events = toolEvents;
                    metadata.pending = true;
                    metadata.statusText = eventData.status === "running"
                        ? t('tools.calling', {name: eventData.name || eventData.tool})
                        : t('tools.completed', {name: eventData.name || eventData.tool});
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "plan_decision") {
                    touchProgress(t('status.preparing_plan'));
                    updateActiveStreamState("running", "plan_decision", t('status.preparing_plan'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    metadata.plan_decision = eventData.decision || null;
                    metadata.pending = true;
                    metadata.statusText = metadata.plan_decision?.enabled ? t('status.preparing_plan') : t('status.direct_exec');
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "plan") {
                    touchProgress(t('status.exec_by_plan'));
                    updateActiveStreamState("running", "plan", t('status.exec_by_plan'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    metadata.execution_plan = eventData.plan || null;
                    metadata.pending = true;
                    metadata.statusText = t('status.exec_by_plan');
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "plan_step") {
                    touchProgress(t('status.advancing_plan'));
                    updateActiveStreamState("running", "plan_step", t('status.advancing_plan'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    const plan = metadata.execution_plan || { title: t('plan.exec_title'), steps: [] };
                    const steps = Array.isArray(plan.steps) ? [...plan.steps] : [];
                    if (Number.isInteger(eventData.index) && eventData.index >= 0) {
                        steps[eventData.index] = eventData.step || steps[eventData.index] || {};
                    }
                    metadata.execution_plan = { ...plan, steps };
                    metadata.pending = true;
                    metadata.statusText = t('status.advancing_plan');
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "changes") {
                    touchProgress(t('status.organizing_changes'));
                    updateActiveStreamState("running", "changes", t('status.organizing_changes'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    metadata.change_summary = eventData.summary || null;
                    metadata.pending = true;
                    metadata.statusText = t('status.organizing_changes');
                    streamingMessages[assistantIndex].metadata = metadata;
                    renderStreamMessages();
                }
                if (eventData.event === "message_replace") {
                    touchProgress(t('status.correcting_tool'));
                    updateActiveStreamState("running", "message_replace", t('status.correcting_tool'));
                    const metadata = streamingMessages[assistantIndex].metadata || {};
                    const currentContent = streamingMessages[assistantIndex].content || "";
                    const nextContent = eventData.message || "";
                    if (currentContent && currentContent !== nextContent) {
                        const revisions = metadata.response_revisions || [];
                        revisions.push({
                            content: currentContent,
                            statusText: metadata.statusText || "",
                            time: Date.now(),
                        });
                        metadata.response_revisions = revisions.slice(-8);
                    }
                    streamingMessages[assistantIndex].content = eventData.message || "";
                    if (eventData.clear_reasoning) {
                        if (metadata.reasoning && !eventData.discard_reasoning) {
                            const history = metadata.reasoning_history || [];
                            history.push({
                                content: metadata.reasoning,
                                time: Date.now(),
                            });
                            metadata.reasoning_history = history.slice(-8);
                        }
                        delete metadata.reasoning;
                    }
                    metadata.pending = true;
                    metadata.statusText = t('status.correcting_tool');
                    streamingMessages[assistantIndex].metadata = metadata;
                    assistantStarted = Boolean(streamingMessages[assistantIndex].content);
                    renderStreamMessages();
                }
                if (eventData.event === "message") {
                    touchProgress(t('status.generating'));
                    updateActiveStreamState("running", "message", t('status.generating'));
                    if (!assistantStarted) {
                        streamingMessages[assistantIndex].content = "";
                        assistantStarted = true;
                    }
                    streamingMessages[assistantIndex].content += eventData.message || "";
                    streamingMessages[assistantIndex].metadata = {
                        ...(streamingMessages[assistantIndex].metadata || {}),
                        pending: true,
                        statusText: t('status.generating'),
                    };
                    renderStreamMessages();
                }
                if (eventData.event === "done") {
                    finished = true;
                    hideStatusBar();
                    upsertConversationSummary(eventData.conversation);
                    if (eventData.context_tokens && state.currentConversationId === conversationId) {
                        state.contextTokens = eventData.context_tokens;
                        state.contextLimit = eventData.context_limit || 0;
                        renderContextBar();
                        renderCurrentWorkspace();
                    }
                    if (state.currentConversationId === conversationId) {
                        const finalMessages = mergeFinalStreamMetadata(
                            eventData.conversation.messages,
                            streamingMessages[assistantIndex],
                        );
                        renderMessages(finalMessages);
                    }
                    renderConversations();
                    if (state.currentConversationId === conversationId) {
                        $("last-task-output").textContent = JSON.stringify(eventData.assistant?.metadata || {}, null, 2);
                    }
                }
                if (eventData.event === "confirm") {
                    // 后端请求用户确认，暂停流并显示确认UI
                    showConfirmUI(eventData.message || t('status.confirm_pause'));
                    updateActiveStreamState("waiting_confirmation", "waiting_confirmation", eventData.message || t('status.waiting_confirm'));
                    streamingMessages[assistantIndex].metadata = {
                        ...(streamingMessages[assistantIndex].metadata || {}),
                        pending: true,
                        waitingConfirmation: true,
                        statusText: eventData.message || t('status.waiting_confirm'),
                    };
                    renderStreamMessages();
                }
            },
            abortController.signal,
        );
        if (!finished) {
            streamingMessages[assistantIndex].metadata = {
                ...(streamingMessages[assistantIndex].metadata || {}),
                pending: false,
            };
            renderStreamMessages();
        }
    } catch (error) {
        if (error.name === "AbortError") {
            streamingMessages[assistantIndex].metadata = {
                ...(streamingMessages[assistantIndex].metadata || {}),
                pending: false,
                statusText: t('status.stopped'),
            };
            if (!streamingMessages[assistantIndex].content) {
                streamingMessages[assistantIndex].content = t('status.stopped_generating');
            }
            renderStreamMessages();
        } else {
            await Promise.allSettled(uploadedAttachments.map((item) => api(`/attachments/${encodeURIComponent(item.id)}`, {
                method: "DELETE",
            })));
            const errorMessages = [
                ...previousMessages,
                {
                    role: "user",
                    content: content || t('attachment.placeholder'),
                    metadata: { attachments: uploadedAttachments },
                },
                { role: "assistant", content: `Error: ${error.message}`, metadata: { error: true } },
            ];
            const activeStream = state.activeStreams.get(conversationId);
            if (activeStream) {
                activeStream.messages = errorMessages;
            }
            if (state.currentConversationId === conversationId) {
                renderMessages(errorMessages);
            }
            showToast(error.message);
        }
    } finally {
        if (progressTimer) {
            clearInterval(progressTimer);
        }
        hideStatusBar();
        state.activeStreams.delete(conversationId);
        state.pendingComposerSubmits.delete(conversationSubmitKey);
        updateSendingState();
        state.abortController = state.activeStreams.get(state.currentConversationId)?.abortController || null;
        syncCurrentConversationStreamStatus();
        renderConversations();
        renderWorkspaces();
        renderCurrentWorkspace();
    }
}

function setSendButtonState(sending) {
    const btn = $("send-btn");
    const input = $("message-input");
    const currentRun = latestActiveRunForConversation(state.currentConversationId);
    const detachedRun = currentRun && !isConversationStreaming();
    if (sending) {
        const hasText = Boolean(input?.value.trim());
        if (detachedRun) {
            btn.textContent = hasText ? t('composer.interrupt') : t('conv.running');
            btn.classList.toggle("stop-mode", hasText);
            btn.disabled = !hasText;
        } else {
            btn.textContent = hasText ? t('composer.interrupt') : t('composer.stop');
            btn.classList.add("stop-mode");
            btn.disabled = false;
        }
        btn.type = "button";
    } else {
        btn.textContent = t('composer.send');
        btn.classList.remove("stop-mode");
        btn.type = "submit";
        btn.disabled = false;
    }
}

async function stopGeneration() {
    const conversationId = state.currentConversationId;
    if (!conversationId) return;
    const activeStream = state.activeStreams.get(conversationId);
    const activeRun = latestActiveRunForConversation(conversationId);
    let runId = activeStream?.runId || activeRun?.id || "";
    if (!runId && activeStream) {
        await refreshActiveRuns();
        runId = latestActiveRunForConversation(conversationId)?.id || "";
    }
    const canStopPersistedRun = runId && !String(runId).startsWith("stream:");
    if (runId) {
        state.locallyStoppedRunIds.add(runId);
    }
    if (activeStream) {
        activeStream.status = "stopped";
        activeStream.stage = "stopped";
        activeStream.message = t('status.stopped');
        activeStream.locallyStopped = true;
        activeStream.updatedAt = new Date().toISOString();
        const pendingAssistant = [...(activeStream.messages || [])]
            .reverse()
            .find((message) => message?.role === "assistant" && message?.metadata?.pending);
        if (pendingAssistant?.metadata) {
            pendingAssistant.metadata.pending = false;
            pendingAssistant.metadata.waitingConfirmation = false;
            pendingAssistant.metadata.statusText = t('status.stopped');
            pendingAssistant.metadata.baseStatusText = t('status.stopped');
        }
    }
    if (runId) {
        state.activeRuns = state.activeRuns.filter((run) => run.id !== runId);
    }
    renderConversations();
    renderWorkspaces();
    renderCurrentWorkspace();
    refreshComposerState();
    const stopRequest = canStopPersistedRun
        ? api(`/runs/${encodeURIComponent(runId)}/actions`, {
            method: "POST",
            body: JSON.stringify({ action: "stop", reason: "user stopped generation" }),
        })
        : Promise.resolve(null);
    if (activeStream?.abortController) {
        activeStream.abortController.abort();
    }
    try {
        await stopRequest;
    } catch (error) {
        if (runId) state.locallyStoppedRunIds.delete(runId);
        await refreshActiveRuns();
        throw error;
    }
    if (!activeStream) {
        await refreshActiveRuns();
    }
}

async function sendConfirmAction(action) {
    if (!state.currentConversationId) return;
    const activeStream = state.activeStreams.get(state.currentConversationId);
    const pendingAssistant = [...(activeStream?.messages || [])]
        .reverse()
        .find((message) => message?.role === "assistant" && message?.metadata?.pending);
    if (pendingAssistant?.metadata) {
        pendingAssistant.metadata.waitingConfirmation = false;
        pendingAssistant.metadata.baseStatusText = action === "continue" ? t('status.continuing') : t('status.stopping');
        pendingAssistant.metadata.statusText = pendingAssistant.metadata.baseStatusText;
        pendingAssistant.metadata.lastProgressAt = Date.now();
    }
    if (activeStream) {
        activeStream.status = "running";
        activeStream.stage = action === "continue" ? "continuing" : "stopping";
        activeStream.message = action === "continue" ? t('status.continuing') : t('status.stopping');
        activeStream.updatedAt = new Date().toISOString();
        renderWorkspaces();
        renderCurrentWorkspace();
    }
    const actionsEl = $("status-bar-actions");
    if (actionsEl) actionsEl.classList.add("hidden");
    const statusText = $("streaming-status-text");
    if (statusText) statusText.textContent = action === "continue" ? t('status.continuing') : t('status.stopping');
    try {
        const result = await api(`/conversations/${state.currentConversationId}/confirm`, {
            method: "POST",
            body: JSON.stringify({ action }),
        });
        if (result?.success === false) {
            showToast(result.error || t('toast.confirm_failed', {error: t('status.waiting_confirm')}));
        }
        await refreshActiveRuns();
        syncPendingConfirmationBar();
    } catch (err) {
        showToast(t('toast.confirm_failed', {error: err.message}));
    }
}

async function streamApi(path, body, onEvent, signal) {
    const response = await fetch(path, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(body),
        signal,
    });
    if (!response.ok || !response.body) {
        const raw = await response.text();
        let payload;
        try {
            payload = raw ? JSON.parse(raw) : {};
        } catch {
            payload = { error: raw || response.statusText };
        }
        throw new Error(payload.error || payload.message || response.statusText);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
            handleStreamLine(line, onEvent);
        }
    }
    if (buffer.trim()) {
        handleStreamLine(buffer, onEvent);
    }
}

function handleStreamLine(line, onEvent) {
    const trimmed = line.trim();
    if (!trimmed) return;
    onEvent(JSON.parse(trimmed));
}

function setSuggestion(value) {
    $("message-input").value = value;
    $("message-input").focus();
    hideMentionMenu();
}

function getMentionContext() {
    const input = $("message-input");
    const position = input.selectionStart ?? input.value.length;
    const beforeCursor = input.value.slice(0, position);
    const match = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
    if (!match) return null;
    const query = match[2] || "";
    return {
        start: position - query.length - 1,
        end: position,
        query,
    };
}

function handleMentionInput() {
    const context = getMentionContext();
    if (!context) {
        hideMentionMenu();
        return;
    }
    state.mention.active = true;
    state.mention.start = context.start;
    state.mention.end = context.end;
    state.mention.query = context.query;
    renderMentionMenu();
    ensureMentionFiles()
        .then(() => {
            if (state.mention.active) renderMentionMenu();
        })
        .catch(() => {});
}

async function ensureMentionFiles() {
    const workspace = getCurrentWorkspace();
    if (!workspace || state.mention.filesWorkspaceId === workspace.id) return;
    state.mention.filesWorkspaceId = workspace.id;
    state.mention.files = [];
    const task = await api("/tool-tasks", {
        method: "POST",
        body: JSON.stringify({
            tool: "code.list_project_files",
            input: {
                path: workspace.path,
                max_files: 80,
            },
            wait: true,
        }),
    });
    state.mention.files = task.output?.files || [];
}

function getMentionCandidates() {
    const workspace = getCurrentWorkspace();
    const candidates = [];
    if (workspace) {
        candidates.push({
            kind: t('mention.project'),
            label: workspace.name,
            detail: workspace.path,
            value: `@项目目录:${workspace.path} `,
        });
    }
    for (const tool of state.tools) {
        candidates.push({
            kind: t('mention.tool'),
            label: tool.name,
            detail: tool.id,
            value: `@工具:${tool.id} `,
        });
    }
    for (const file of state.mention.files) {
        candidates.push({
            kind: t('mention.file'),
            label: file.path,
            detail: `${file.extension || t('mention.file')} · ${formatBytes(file.size)}`,
            value: `@文件:${file.path} `,
        });
    }

    const query = state.mention.query.trim().toLowerCase();
    const filtered = query
        ? candidates.filter((item) => `${item.kind} ${item.label} ${item.detail}`.toLowerCase().includes(query))
        : candidates;
    return filtered.slice(0, 12);
}

function renderMentionMenu() {
    const menu = $("mention-menu");
    const candidates = getMentionCandidates();
    state.mention.candidates = candidates;
    menu.classList.remove("hidden");
    if (!candidates.length) {
        menu.innerHTML = `<div class="mention-empty">${t('mention.no_match')}</div>`;
        return;
    }
    menu.innerHTML = candidates.map((item, index) => `
        <button type="button" class="mention-item" data-mention-index="${index}">
            <span class="mention-kind">${escapeHtml(item.kind)}</span>
            <span class="mention-label">${escapeHtml(item.label)}</span>
            <span class="mention-detail">${escapeHtml(item.detail)}</span>
        </button>
    `).join("");
}

function insertMention(index) {
    const candidate = state.mention.candidates?.[index];
    if (!candidate) return;
    const input = $("message-input");
    const start = state.mention.start;
    const end = state.mention.end;
    input.value = `${input.value.slice(0, start)}${candidate.value}${input.value.slice(end)}`;
    const cursor = start + candidate.value.length;
    input.focus();
    input.setSelectionRange(cursor, cursor);
    hideMentionMenu();
}

function hideMentionMenu() {
    state.mention.active = false;
    state.mention.start = -1;
    state.mention.end = -1;
    state.mention.query = "";
    state.mention.candidates = [];
    $("mention-menu").classList.add("hidden");
}

function formatBytes(value) {
    const size = Number(value || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function renderExecutionPlan(message) {
    const plan = message.metadata?.execution_plan;
    if (!plan || !Array.isArray(plan.steps) || !plan.steps.length) return "";
    const decision = message.metadata?.plan_decision;
    const sourceLabel = decision?.source === "model" ? t('plan.source_auto') : decision?.mode === "always" ? t('plan.source_manual') : t('plan.source_plan');
    return `
        <details class="plan-block" open>
            <summary>
                <span>${escapeHtml(plan.title || t('plan.exec_title'))}</span>
                <em>${escapeHtml(sourceLabel)}</em>
            </summary>
            <div class="plan-steps">
                ${plan.steps.map((step, index) => {
                    const status = step.status || "pending";
                    const labels = {
                        pending: t('plan.pending'),
                        running: t('plan.running'),
                        completed: t('plan.completed'),
                        failed: t('plan.failed'),
                        skipped: t('plan.skipped'),
                    };
                    return `
                        <div class="plan-step ${status}">
                            <span class="plan-step-index">${index + 1}</span>
                            <div class="plan-step-body">
                                <div class="plan-step-title">
                                    <strong>${escapeHtml(step.title || t('plan.step', {n: index + 1}))}</strong>
                                    <span>${escapeHtml(labels[status] || status)}</span>
                                </div>
                                ${step.description ? `<div class="plan-step-desc">${escapeHtml(step.description)}</div>` : ""}
                                ${step.tool_hint || step.tool ? `<div class="plan-step-tool">${escapeHtml(step.tool || step.tool_hint)}</div>` : ""}
                                ${step.error ? `<div class="plan-step-error">${escapeHtml(step.error)}</div>` : ""}
                            </div>
                        </div>
                    `;
                }).join("")}
            </div>
        </details>
    `;
}

function renderLiveStatus(message) {
    const metadata = message.metadata || {};
    if (!metadata.pending) return "";
    const text = metadata.statusText || metadata.baseStatusText || t('status.thinking');
    const elapsed = Number.isFinite(Number(metadata.elapsedSeconds))
        ? Number(metadata.elapsedSeconds)
        : elapsedSeconds(metadata.startedAt || Date.now());
    return `
        <div class="message-live-status">
            <span class="message-live-dot"></span>
            <span>${escapeHtml(text)}</span>
            ${metadata.waitingConfirmation ? "" : `<em>${formatElapsed(elapsed)}</em>`}
        </div>
    `;
}

function renderReasoning(message) {
    const reasoning = message.metadata?.reasoning;
    if (!reasoning) return "";
    const isPending = Boolean(message.metadata?.pending);
    return `
        <details class="reasoning-block ${isPending ? "streaming" : ""}" ${isPending ? "open" : ""}>
            <summary>
                <span>${isPending ? t('status.thinking') : t('status.reasoning_block_title')}</span>
                ${isPending ? `<span class="reasoning-live">${t('status.reasoning_live')}</span>` : ""}
            </summary>
            <div class="reasoning-content">${formatMessageContent(reasoning)}</div>
        </details>
    `;
}

function renderProcessHistory(message) {
    const revisions = message.metadata?.response_revisions || [];
    const reasoningHistory = message.metadata?.reasoning_history || [];
    if (!revisions.length && !reasoningHistory.length) return "";
    const count = revisions.length + reasoningHistory.length;
    const revisionRows = revisions.map((item, index) => `
        <div class="process-history-item">
            <strong>${t('process.draft', {n: index + 1})}</strong>
            ${item.statusText ? `<em>${escapeHtml(item.statusText)}</em>` : ""}
            <div class="process-history-content">${formatMessageContent(item.content || "")}</div>
        </div>
    `).join("");
    const reasoningRows = reasoningHistory.map((item, index) => `
        <div class="process-history-item">
            <strong>${t('process.reasoning_snapshot', {n: index + 1})}</strong>
            <div class="process-history-content">${formatMessageContent(item.content || "")}</div>
        </div>
    `).join("");
    return `
        <details class="process-history-block">
            <summary>
                <span>${t('process.history_title')}</span>
                <em>${t('process.history_count', {count})}</em>
            </summary>
            <div class="process-history-list">
                ${revisionRows}
                ${reasoningRows}
            </div>
        </details>
    `;
}

function renderToolEvents(message) {
    const events = message.metadata?.tool_events || [];
    if (!events.length) return "";
    return `
        <div class="tool-events">
            ${events.map((item) => {
                const statusLabel = item.status === "running"
                    ? t('tools.calling_short')
                    : item.status === "success"
                        ? t('tools.called')
                        : item.status === "partial"
                            ? t('tools.call_partial')
                            : t('tools.call_failed');
                const header = `
                    <div class="tool-event ${item.status === "failure" ? "failed" : ""} ${item.status === "partial" ? "partial" : ""}">
                        <span>${escapeHtml(statusLabel)}</span>
                        <strong>${escapeHtml(item.name || item.tool)}</strong>
                    </div>
                `;
                const progressHtml = renderToolProgress(item);
                const logsHtml = renderToolLogs(item);
                const outputHtml = renderToolOutput(item);
                return header + progressHtml + logsHtml + outputHtml;
            }).join("")}
        </div>
    `;
}

function findToolEventIndex(toolEvents, eventData) {
    if (!Array.isArray(toolEvents)) return -1;
    if (eventData.task_id) {
        const taskIndex = toolEvents.findIndex((item) => item.task_id === eventData.task_id);
        if (taskIndex >= 0) return taskIndex;
    }
    for (let index = toolEvents.length - 1; index >= 0; index -= 1) {
        if (toolEvents[index].status === "running"
            && (!eventData.tool || toolEvents[index].tool === eventData.tool)) {
            return index;
        }
    }
    return -1;
}

function renderToolProgress(item) {
    const progress = item.progress && typeof item.progress === "object" ? item.progress : {};
    const taskProgress = progress.tool_task && typeof progress.tool_task === "object" ? progress.tool_task : progress;
    if (!taskProgress || taskProgress.kind !== "tool_task_progress") return "";
    const command = taskProgress.command && typeof taskProgress.command === "object" ? taskProgress.command : {};
    const flags = taskProgress.flags && typeof taskProgress.flags === "object" ? taskProgress.flags : {};
    const counts = taskProgress.counts && typeof taskProgress.counts === "object" ? taskProgress.counts : {};
    const lastHeartbeat = taskProgress.last_heartbeat && typeof taskProgress.last_heartbeat === "object" ? taskProgress.last_heartbeat : {};
    const role = command.role || "";
    const chips = [];
    const roleLabel = toolRoleLabel(role);
    if (roleLabel) chips.push(roleLabel);
    const elapsedChip = formatToolElapsedChip(
        toolEventElapsedSeconds(item, taskProgress),
        item.status === "running",
    );
    if (elapsedChip) chips.push(elapsedChip);
    if (Number.isFinite(Number(taskProgress.stale_seconds)) && Number(taskProgress.stale_seconds) > 0) {
        chips.push(t('tools.progress_stale', {seconds: Number(taskProgress.stale_seconds)}));
    }
    if (Number.isFinite(Number(counts.output_events)) && Number(counts.output_events) > 0) {
        chips.push(t('tools.progress_output_events', {count: Number(counts.output_events)}));
    }
    if (flags.has_heartbeat) chips.push(t('tools.progress_heartbeat_seen'));
    if (taskProgress.can_cancel) chips.push(t('tools.can_cancel'));
    if (!chips.length) return "";
    const lastSilent = Number(lastHeartbeat.silent_seconds);
    const note = Number.isFinite(lastSilent) && lastSilent > 0
        ? `<span>${escapeHtml(t('tools.progress_no_output', {seconds: Math.round(lastSilent)}))}</span>`
        : "";
    return `
        <div class="tool-progress-summary">
            ${chips.map((chip) => `<em>${escapeHtml(chip)}</em>`).join("")}
            ${note}
        </div>
    `;
}

function toolRoleLabel(role) {
    if (role === "dependency_install") return t('tools.role_dependency_install');
    if (role === "preview_service") return t('tools.role_preview_service');
    if (role === "service") return t('tools.role_service');
    if (role === "command") return t('tools.role_command');
    return role || "";
}

function renderToolLogs(item) {
    const logs = item.logs || [];
    if (!logs.length) return "";
    const isRunning = item.status === "running";
    const rows = logs.map((log) => {
        const stream = log.data?.stream === "stderr" ? "stderr" : "";
        return `<span class="tool-log-line ${stream}">${escapeHtml(log.message || "")}</span>`;
    }).join("\n");
    return `
        <details class="tool-live-logs" ${isRunning ? "open" : ""}>
            <summary>${escapeHtml(t('tools.live_output'))}<em>${logs.length}</em></summary>
            <pre>${rows}</pre>
        </details>
    `;
}

function renderToolOutput(item) {
    if (item.status === "failure") {
        const path = item.input?.path ? `<div>${t('tools.path')}${escapeHtml(item.input.path)}</div>` : "";
        const task = item.task_id ? `<div>${t('tools.task')}${escapeHtml(item.task_id)}</div>` : "";
        const error = item.error || t('tools.failure_default');
        return `
            <div class="tool-error-block">
                <strong>${t('tools.failure_reason')}</strong>
                <div>${escapeHtml(error)}</div>
                ${path}
                ${task}
            </div>
        `;
    }
    if (!item.output || item.status === "running") return "";
    const o = item.output;
    if (o.type === "shell") {
        const exitLabel = o.exit_code === 0 ? t('tools.exit_code_0') : t('tools.exit_code', {code: o.exit_code});
        const stdout = o.stdout ? `<pre class="shell-output">${escapeHtml(o.stdout)}</pre>` : "";
        const stderr = o.stderr ? `<pre class="shell-stderr">${escapeHtml(o.stderr)}</pre>` : "";
        return `<div class="tool-output-shell"><div class="shell-exit ${o.exit_code === 0 ? "" : "exit-error"}">${exitLabel}</div>${stdout}${stderr}</div>`;
    }
    if (o.type === "diff") {
        if (!o.diff_preview) return "";
        const pathHeader = o.path ? `<div class="tool-output-info">${t('tools.path')}${escapeHtml(o.path)}</div>` : "";
        const lines = o.diff_preview.split("\n").map((line) => {
            const cls = line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : line.startsWith("@@") ? "diff-hunk" : "";
            return `<span class="diff-line ${cls}">${escapeHtml(line)}</span>`;
        }).join("\n");
        return `${pathHeader}${renderBackupBadge(o.backup)}<pre class="diff-block">${lines}</pre>`;
    }
    if (o.type === "file_write") {
        const label = o.created ? t('tools.file_created') : t('tools.file_written');
        const size = Number.isFinite(Number(o.size)) ? ` · ${Number(o.size)} bytes` : "";
        return `<div class="tool-output-info">${label}：${escapeHtml(o.path || "")}${size}</div>${renderFileWriteDetail(o)}${renderBackupBadge(o.backup)}`;
    }
    if (o.type === "bulk_replace") {
        const files = o.changed_files || [];
        const action = o.dry_run ? t('bulk.match') : t('bulk.replace');
        const total = Number.isFinite(Number(o.replacement_count)) ? Number(o.replacement_count) : 0;
        const fileCount = Number.isFinite(Number(o.changed_file_count)) ? Number(o.changed_file_count) : files.length;
        const rows = files.slice(0, 20).map((file) => `
            <div class="bulk-replace-row">
                <span>${escapeHtml(file.path || "")}</span>
                <em>${t('bulk.occurrences', {count: Number(file.occurrences || 0)})}</em>
            </div>
        `).join("");
        const more = o.truncated ? `<div class="bulk-replace-more">${t('bulk.truncated')}</div>` : "";
        return `
            <div class="bulk-replace-block">
                <div class="bulk-replace-head">${t('bulk.files_total', {action, files: fileCount, total})}</div>
                ${renderBackupBadge(o.backup)}
                <div class="bulk-replace-pair"><code>${escapeHtml(o.old_text || "")}</code><span>→</span><code>${escapeHtml(o.new_text || "")}</code></div>
                ${rows ? `<div class="bulk-replace-list">${rows}</div>` : ""}
                ${more}
            </div>
        `;
    }
    if (o.type === "git_status") {
        if (!o.files || !o.files.length) return `<div class="tool-output-info">${t('tools.working_clean')}</div>`;
        const rows = o.files.map((f) => {
            const status = f.status || `${f.x || ""}${f.y || ""}`;
            return `<span class="git-status-row"><span class="git-xy">${escapeHtml(status)}</span> ${escapeHtml(f.path)}</span>`;
        }).join("\n");
        return `<pre class="git-status-block">${rows}</pre>`;
    }
    if (o.type === "git_log") {
        if (!o.commits || !o.commits.length) return "";
        const rows = o.commits.map((c) => `<span class="git-log-row"><span class="git-hash">${escapeHtml((c.hash || "").slice(0, 7))}</span> ${escapeHtml(c.message || "")}</span>`).join("\n");
        return `<pre class="git-log-block">${rows}</pre>`;
    }
    if (o.type === "web") {
        const title = o.title ? `<strong>${escapeHtml(o.title)}</strong>` : "";
        const url = o.final_url || o.url || "";
        const links = Array.isArray(o.links) && o.links.length
            ? `<div class="web-link-list">${o.links.slice(0, 8).map((link) => `
                <div class="web-link-row">
                    <span>${escapeHtml(link.text || link.url || "")}</span>
                    <code>${escapeHtml(link.url || "")}</code>
                </div>
            `).join("")}</div>`
            : "";
        const text = o.text ? `<pre class="web-text-preview">${escapeHtml(o.text)}</pre>` : "";
        return `
            <div class="tool-output-web">
                <div class="tool-output-info">HTTP ${escapeHtml(o.status_code || "")} · ${escapeHtml(url)}</div>
                ${title}
                ${text}
                ${links}
            </div>
        `;
    }
    return "";
}

function renderFileWriteDetail(o) {
    const rows = [];
    if (o.status === "partial_resumable" || o.partial_resumable) {
        rows.push(t('tools.partial_resumable'));
    } else if (o.complete === false && o.status) {
        rows.push(t('tools.partial_output'));
    }
    if (o.translated_paragraph_count !== undefined && o.target_nonempty_goal !== undefined) {
        rows.push(t('tools.translation_progress', {
            done: Number(o.translated_paragraph_count || 0),
            total: Number(o.target_nonempty_goal || 0),
        }));
    }
    if (o.source_chars_done !== undefined && o.source_chars_total) {
        const percent = Math.round((Number(o.source_chars_done || 0) / Number(o.source_chars_total || 1)) * 1000) / 10;
        rows.push(t('tools.char_progress', {percent}));
    }
    if (o.manifest_path) {
        rows.push(`${t('tools.manifest')}${o.manifest_path}`);
    }
    if (o.stopped_reason) {
        rows.push(`${t('tools.stopped_reason')}${o.stopped_reason}`);
    }
    if (!rows.length) return "";
    return `<div class="tool-output-detail">${rows.map((row) => `<div>${escapeHtml(row)}</div>`).join("")}</div>`;
}

function renderBackupBadge(backup) {
    if (!backup?.id) return "";
    const count = Number(backup.file_count || 0);
    return `<div class="backup-badge"><div>${t('backup.badge', {count})}</div>${renderBackupFiles(backup, 3)}</div>`;
}

function renderExecutionNotice(message) {
    const notice = message.metadata?.execution_notice;
    if (!notice?.message) return "";
    const failed = notice.failed_tools || [];
    return `
        <div class="execution-notice">
            <strong>${t('exec.validation')}</strong>
            <div>${escapeHtml(notice.message)}</div>
            ${failed.length ? `
                <div class="execution-failures">
                    ${failed.map((item) => `
                        <div class="execution-failure-row">
                            <span>${escapeHtml(item.name || item.tool || t('exec.write_tool'))}</span>
                            <code>${escapeHtml(item.path || "")}</code>
                            <em>${escapeHtml(item.error || "")}</em>
                        </div>
                    `).join("")}
                </div>
            ` : ""}
        </div>
    `;
}

function renderChangeSummary(message) {
    const summary = message.metadata?.change_summary;
    const files = summary?.files || [];
    if (!files.length) return "";
    const title = summary.clean || summary.source === "tool-events" ? t('changes.touched') : t('changes.changed');
    const meta = [];
    if (summary.branch) meta.push(t('changes.branch', {branch: summary.branch}));
    const dirtyCount = summary.total_dirty_count;
    if (dirtyCount !== null && dirtyCount !== undefined && dirtyCount !== "" && Number.isFinite(Number(dirtyCount))) {
        meta.push(t('changes.dirty', {count: Number(dirtyCount)}));
    }
    if (summary.truncated) meta.push(t('changes.truncated'));
    return `
        <details class="change-summary" open>
            <summary>
                <span>${escapeHtml(title)}</span>
                <em>${escapeHtml(meta.join(" · "))}</em>
            </summary>
            <div class="change-file-list">
                ${files.map((file) => `
                    <div class="change-file-row">
                        <span class="change-status">${escapeHtml(file.status || "")}</span>
                        <span class="change-path">${escapeHtml(file.path || "")}</span>
                    </div>
                `).join("")}
            </div>
        </details>
    `;
}

function formatMessageContent(value) {
    const text = String(value ?? "");
    if (!text.trim()) return "";
    const parts = [];
    const fencePattern = /```([\w-]*)\n?([\s\S]*?)```/g;
    let lastIndex = 0;
    let match;
    while ((match = fencePattern.exec(text)) !== null) {
        if (match.index > lastIndex) {
            parts.push(formatMarkdownText(text.slice(lastIndex, match.index)));
        }
        const lang = match[1] ? `<div class="code-lang">${escapeHtml(match[1])}</div>` : "";
        parts.push(`<pre class="code-block">${lang}<code>${escapeHtml(match[2].trim())}</code></pre>`);
        lastIndex = fencePattern.lastIndex;
    }
    if (lastIndex < text.length) {
        parts.push(formatMarkdownText(text.slice(lastIndex)));
    }
    return parts.join("");
}

function formatMarkdownText(text) {
    const lines = text.replace(/\r\n/g, "\n").split("\n");
    let html = "";
    let inList = false;
    for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        const escaped = escapeHtml(line);
        if (!line.trim()) {
            if (inList) {
                html += "</ul>";
                inList = false;
            }
            continue;
        }
        const heading = escaped.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
            if (inList) {
                html += "</ul>";
                inList = false;
            }
            const level = heading[1].length;
            html += `<h${level}>${formatInline(heading[2])}</h${level}>`;
            continue;
        }
        const listItem = escaped.match(/^\s*[-*]\s+(.+)$/);
        if (listItem) {
            if (!inList) {
                html += "<ul>";
                inList = true;
            }
            html += `<li>${formatInline(listItem[1])}</li>`;
            continue;
        }
        if (inList) {
            html += "</ul>";
            inList = false;
        }
        html += `<p>${formatInline(escaped)}</p>`;
    }
    if (inList) html += "</ul>";
    return html;
}

function formatInline(html) {
    return html
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

document.addEventListener("click", async (event) => {
    const restoreButton = event.target.closest("[data-restore-backup]");
    if (restoreButton) {
        event.stopPropagation();
        await restoreBackup(restoreButton.dataset.restoreBackup).catch((error) => showToast(error.message));
        return;
    }

    const mentionButton = event.target.closest("[data-mention-index]");
    if (mentionButton) {
        insertMention(Number(mentionButton.dataset.mentionIndex));
        return;
    }

    const menuButton = event.target.closest("[data-workspace-menu]");
    if (menuButton) {
        event.stopPropagation();
        const workspaceId = menuButton.dataset.workspaceMenu;
        state.openWorkspaceMenuId = state.openWorkspaceMenuId === workspaceId ? "" : workspaceId;
        renderWorkspaces();
        return;
    }

    const pinButton = event.target.closest("[data-workspace-pin]");
    if (pinButton) {
        event.stopPropagation();
        toggleWorkspacePin(pinButton.dataset.workspacePin);
        return;
    }

    const openButton = event.target.closest("[data-workspace-open]");
    if (openButton) {
        event.stopPropagation();
        await openWorkspaceInExplorer(openButton.dataset.workspaceOpen).catch((error) => showToast(error.message));
        return;
    }

    const removeButton = event.target.closest("[data-workspace-remove]");
    if (removeButton) {
        event.stopPropagation();
        state.openWorkspaceMenuId = "";
        await removeWorkspace(removeButton.dataset.workspaceRemove);
        return;
    }

    const workspaceButton = event.target.closest("[data-workspace-id]");
    if (workspaceButton) {
        state.currentWorkspaceId = workspaceButton.dataset.workspaceId;
        state.currentConversationId = "";
        localStorage.setItem("lit_workspace_id", state.currentWorkspaceId);
        localStorage.removeItem("lit_conversation_id");
        renderWorkspaces();
        renderCurrentWorkspace();
        await loadConversations();
        return;
    }

    const deleteConvButton = event.target.closest("[data-delete-conversation]");
    if (deleteConvButton) {
        event.stopPropagation();
        const convId = deleteConvButton.dataset.deleteConversation;
        if (confirm(t('conv.confirm_delete'))) {
            await deleteConversation(convId);
        }
        return;
    }

    const conversationButton = event.target.closest("[data-conversation-id]");
    if (conversationButton) {
        await loadConversation(conversationButton.dataset.conversationId);
        return;
    }

    const suggestion = event.target.closest("[data-suggestion]");
    if (suggestion) {
        setSuggestion(suggestion.dataset.suggestion);
        return;
    }

    if (state.openWorkspaceMenuId && !event.target.closest(".workspace-menu-wrap")) {
        state.openWorkspaceMenuId = "";
        renderWorkspaces();
    }

    if (!event.target.closest("#composer")) {
        hideMentionMenu();
    }
});

function on(id, eventName, handler) {
    const el = $(id);
    if (el) el.addEventListener(eventName, handler);
}

on("backend-login-btn", "click", () => loginBackend().catch((error) => setStatus("backend-state", error.message)));
on("pick-workspace-btn", "click", () => pickWorkspace().catch((error) => showToast(error.message)));
on("new-conversation-btn", "click", () => newConversation().catch((error) => showToast(error.message)));
on("focus-search-btn", "click", () => $("conversation-search-input")?.focus());
on("open-settings-btn", "click", () => openAuxiliaryPage("/settings-page"));
on("open-plugins-btn", "click", () => openAuxiliaryPage("/plugins-page"));
on("open-mcp-services-btn", "click", () => openAuxiliaryPage("/mcp-services-page"));
on("open-automation-btn", "click", () => openAuxiliaryPage("/automation-page"));
on("open-task-history-btn", "click", () => {
    openTaskHistoryDialog();
});
on("close-task-history-btn", "click", () => $("task-history-dialog")?.close());
on("task-history-search-input", "input", (event) => {
    state.taskHistory.query = event.target.value || "";
    state.taskHistory.page = 1;
    loadTaskHistoryPage().catch((error) => showToast(error.message));
});
on("task-history-prev-btn", "click", () => {
    state.taskHistory.page = Math.max(1, state.taskHistory.page - 1);
    loadTaskHistoryPage().catch((error) => showToast(error.message));
});
on("task-history-next-btn", "click", () => {
    state.taskHistory.page += 1;
    loadTaskHistoryPage().catch((error) => showToast(error.message));
});
on("task-history-list", "click", (event) => {
    const button = event.target.closest("[data-run-action]");
    if (!button) return;
    runTaskHistoryAction(button.dataset.runAction, button.dataset.runId, button)
        .catch((error) => showToast(error.message));
});
on("task-workbench", "click", (event) => {
    const button = event.target.closest("[data-workbench-action]");
    if (!button) return;
    handleWorkbenchPathAction(button)
        .catch((error) => showToast(error.message));
});
on("open-login-btn", "click", () => $("login-dialog").showModal());
on("logout-btn", "click", () => logoutBackend());
on("source-update-btn", "click", () => openSourceUpdateDialog());
on("refresh-source-update-btn", "click", () => loadSourceUpdate({ silent: false }).catch((error) => showToast(error.message)));
on("copy-source-update-command-btn", "click", () => copySourceUpdateCommand().catch((error) => showToast(error.message)));
on("close-source-update-btn", "click", () => $("source-update-dialog")?.close());
on("close-source-update-footer-btn", "click", () => $("source-update-dialog")?.close());
on("conversation-search-input", "input", (event) => {
    state.search = event.target.value;
    renderConversations();
});
on("message-input", "input", () => {
    handleMentionInput();
    refreshComposerState();
});
on("message-input", "click", () => handleMentionInput());
on("message-input", "paste", (event) => {
    const items = event.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (let i = 0; i < items.length; i++) {
        if (items[i].kind === "file") {
            const file = items[i].getAsFile();
            if (file) files.push(file);
        }
    }
    if (files.length) {
        event.preventDefault();
        handleAttachmentFiles(files);
    }
});
on("message-input", "keyup", (event) => {
    if (event.key === "Escape") {
        hideMentionMenu();
        return;
    }
    handleMentionInput();
});
on("model-select", "change", (event) => {
    state.model = event.target.value;
    localStorage.setItem("lit_model", state.model);
    renderCurrentWorkspace();
    renderModelState();
});
on("save-settings-btn", "click", () => saveSettings().catch((error) => showToast(error.message)));
on("refresh-backups-btn", "click", () => loadBackups().catch((error) => showToast(error.message)));
on("restore-latest-backup-btn", "click", () => restoreLatestBackup().catch((error) => showToast(error.message)));
on("clear-backups-btn", "click", () => clearBackups().catch((error) => showToast(error.message)));
on("backend-url-input", "change", (event) => {
    state.backendUrl = event.target.value.trim().replace(/\/+$/, "");
    localStorage.setItem("lit_backend_url", state.backendUrl);
});
on("composer", "submit", (event) => sendMessage(event).catch((error) => showToast(error.message)));
on("send-btn", "click", (event) => {
    if (isComposerSubmitPending()) {
        event.preventDefault();
        return;
    }
    const activeRun = latestActiveRunForConversation(state.currentConversationId);
    if (isConversationStreaming() || activeRun) {
        event.preventDefault();
        const input = $("message-input");
        const content = input?.value.trim() || "";
        if (content) {
            sendGuidance(state.currentConversationId, content)
                .then(() => {
                    input.value = "";
                    refreshComposerState();
                })
                .catch((error) => showToast(error.message));
            return;
        }
        stopGeneration().catch((error) => showToast(error.message));
    }
});
on("message-input", "keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        if (state.mention.active) return;
        event.preventDefault();
        $("composer").dispatchEvent(new Event("submit", { cancelable: true }));
    }
});
on("upload-attachment-btn", "click", () => $("attachment-file-input")?.click());
on("access-scope-btn", "click", () => cycleAccessScope());
on("plan-mode-btn", "click", () => cyclePlanExecutionMode());
on("confirmation-mode-btn", "click", () => cycleConfirmationPolicy());
on("token-battery", "click", () => compressContext().catch((error) => showToast(error.message)));
on("confirm-continue-btn", "click", () => sendConfirmAction("continue"));
on("confirm-cancel-btn", "click", () => sendConfirmAction("cancel"));
on("attachment-file-input", "change", (event) => {
    handleAttachmentFiles(Array.from(event.target.files || []));
});

window.addEventListener("beforeunload", (event) => {
    if (!hasActiveStreams()) return;
    event.preventDefault();
    event.returnValue = "";
});

window.addEventListener("pageshow", () => {
    refreshActiveRuns().catch((error) => console.warn("pageshow refreshActiveRuns failed:", error));
});

window.addEventListener("focus", () => {
    refreshActiveRuns().catch((error) => console.warn("focus refreshActiveRuns failed:", error));
});

document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    refreshActiveRuns().catch((error) => console.warn("visibility refreshActiveRuns failed:", error));
});

if ($("backend-url-input")) $("backend-url-input").value = state.backendUrl;
if ($("model-select")) $("model-select").value = state.model;
renderAuthState();

function handleInitialRouteIntent() {
    const params = new URLSearchParams(window.location.search || "");
    let shouldCleanUrl = false;
    if (params.get("open_tasks") === "1") {
        shouldCleanUrl = true;
        openTaskHistoryDialog();
    }
    if (params.get("start_prepared") === "1") {
        shouldCleanUrl = true;
        const raw = localStorage.getItem("lit_pending_prepared_run") || "";
        localStorage.removeItem("lit_pending_prepared_run");
        if (raw) {
            try {
                const prepared = JSON.parse(raw);
                startPreparedRun(prepared).catch((error) => showToast(error.message));
            } catch (error) {
                showToast(t('tasks.prepared'));
            }
        }
    }
    if (shouldCleanUrl) {
        window.history.replaceState({}, "", window.location.pathname || "/");
    }
}

loadAll().then(() => {
    handleInitialRouteIntent();
}).catch((error) => {
    showToast(error.message);
    renderMessages([]);
});
setInterval(() => {
    refreshActiveRuns();
}, 5000);

function showToast(message) {
    const existing = document.querySelector(".toast");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function handleAttachmentFiles(files) {
    for (const file of files) {
        if (state.pendingAttachments.length >= 8) {
            showToast(t('attachment.max_count'));
            break;
        }
        const limit = file.type.startsWith("image/") ? 10 * 1024 * 1024 : 25 * 1024 * 1024;
        if (file.size > limit) {
            showToast(t('attachment.too_large', {name: file.name}));
            continue;
        }
        state.pendingAttachments.push({
            file,
            previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : "",
        });
    }
    const input = $("attachment-file-input");
    if (input) input.value = "";
    renderAttachmentPreview();
}

function renderAttachmentPreview() {
    const preview = $("attachment-preview");
    if (!preview) return;
    if (!state.pendingAttachments.length) {
        preview.classList.add("hidden");
        preview.innerHTML = "";
        return;
    }
    preview.classList.remove("hidden");
    preview.innerHTML = state.pendingAttachments.map((item, index) => `
        <div class="attachment-preview-item">
            ${item.previewUrl
                ? `<img src="${item.previewUrl}" alt="${t('attachment.preview')}">`
                : `<span class="attachment-file-icon">DOC</span>`}
            <span class="attachment-preview-name" title="${escapeHtml(item.file.name)}">${escapeHtml(item.file.name)}</span>
            <button type="button" class="attachment-preview-remove" data-attachment-index="${index}" title="${t('attachment.remove')}">×</button>
        </div>
    `).join("");
    preview.querySelectorAll("[data-attachment-index]").forEach((button) => {
        button.addEventListener("click", () => removePendingAttachment(Number(button.dataset.attachmentIndex)));
    });
}

function removePendingAttachment(index) {
    const [removed] = state.pendingAttachments.splice(index, 1);
    if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
    renderAttachmentPreview();
}

function clearAttachmentUpload() {
    state.pendingAttachments.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    });
    state.pendingAttachments = [];
    const fileInput = $("attachment-file-input");
    if (fileInput) fileInput.value = "";
    renderAttachmentPreview();
}

async function uploadAttachmentFiles(conversationId, workspaceId, files) {
    const uploaded = [];
    try {
        for (const file of files) {
            const form = new FormData();
            form.append("workspace_id", workspaceId);
            form.append("conversation_id", conversationId);
            form.append("file", file, file.name);
            uploaded.push(await api("/attachments", {method: "POST", body: form}));
        }
        return uploaded;
    } catch (error) {
        await Promise.allSettled(uploaded.map((item) => api(`/attachments/${encodeURIComponent(item.id)}`, {
            method: "DELETE",
        })));
        throw error;
    }
}

function renderMessageAttachments(message) {
    const attachments = Array.isArray(message.metadata?.attachments) ? message.metadata.attachments : [];
    if (!attachments.length) return "";
    return `
        <div class="message-attachments">
            ${attachments.map((item) => item.is_image
                ? `<a class="message-image-attachment" href="${item.content_url}" target="_blank" rel="noopener"><img src="${item.content_url}" alt="${escapeHtml(item.name || t('attachment.file'))}"></a>`
                : `<a class="message-file-attachment" href="${item.content_url}" target="_blank" rel="noopener"><span class="attachment-file-icon">DOC</span><span>${escapeHtml(item.name || t('attachment.file'))}</span><small>${formatFileSize(item.size || 0)}</small></a>`
            ).join("")}
        </div>
    `;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function saveSettings() {
    const providers = {};
    const volcengineKey = $("volcengine-key-input").value.trim();
    const qwenKey = $("qwen-key-input").value.trim();
    if (volcengineKey) {
        providers.volcengine = { api_key: volcengineKey };
    }
    if (qwenKey) {
        providers.qwen = { api_key: qwenKey };
    }
    state.settings = await api("/settings", {
        method: "POST",
        body: JSON.stringify({
            default_model: state.model,
            access_scope: $("access-scope-input") ? $("access-scope-input").value : state.accessScope,
            planning_policy: $("planning-policy-input") ? $("planning-policy-input").value : state.planningPolicy,
            confirmation_policy: $("confirmation-policy-input") ? $("confirmation-policy-input").value : state.confirmationPolicy,
            backups: {
                enabled: $("backup-enabled-input") ? $("backup-enabled-input").checked : true,
                keep_rounds: $("backup-keep-input") ? Number($("backup-keep-input").value || 50) : 50,
            },
            providers,
        }),
    });
    $("volcengine-key-input").value = "";
    $("qwen-key-input").value = "";
    state.accessScope = normalizeAccessScope(state.settings.access_scope || state.accessScope);
    state.planningPolicy = normalizePlanningPolicy(state.settings.planning_policy || state.planningPolicy);
    state.confirmationPolicy = normalizeConfirmationPolicy(state.settings.confirmation_policy || state.confirmationPolicy);
    localStorage.setItem("lit_access_scope", state.accessScope);
    localStorage.setItem("lit_planning_policy", state.planningPolicy);
    localStorage.setItem("lit_confirmation_policy", state.confirmationPolicy);
    renderSettings();
    renderAccessScopeControl();
    renderPlanExecutionControl();
    renderConfirmationExecutionControl();
    $("settings-dialog").close();
    showToast(t('toast.settings_saved'));
}

// 初始化主页语言选择器。
(function initLanguageSelect() {
    const select = $("language-select");
    if (!select) return;
    select.value = getLocale();
    select.addEventListener("change", () => {
        setLocale(select.value);
        loadAll().catch((error) => showToast(error.message));
    });
    window.addEventListener("locale-changed", (event) => {
        if (event.detail?.locale !== select.value) {
            select.value = getLocale();
        }
    });
})();
