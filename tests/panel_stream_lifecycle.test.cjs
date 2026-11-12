const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../runtime/panel/static/panel.js'), 'utf8');
const functions = [
    'isConversationStreaming', 'composerSubmitKey', 'isComposerSubmitPending', 'isRunActive',
    'activeRunsForConversation', 'latestActiveRunForConversation', 'activeRunLabel',
    'formatRunUpdated', 'refreshActiveRuns', 'reconcileCompletedStream', 'syncPersistentRunStatusBar',
    'updateSendingState', 'refreshComposerState', 'syncCurrentConversationStreamStatus',
    'elapsedSeconds', 'formatElapsed', 'mergeFinalStreamMetadata', 'sendMessage', 'setSendButtonState',
].map((name) => {
    const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, 'm'));
    assert(start >= 0, name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
}).join('\n');

function setup(mode = 'hang') {
    const run = { id: 'run-1', conversation_id: 'conv', workspace_id: 'workspace', status: 'success', stage: 'done' };
    const final = { id: 'conv', context_tokens: 23, context_limit: 128000, messages: [
        { role: 'user', content: '优化住宅' },
        { role: 'assistant', content: '模型原文：已保存。', metadata: { run_id: run.id } },
    ] };
    const state = {
        currentConversationId: 'conv', currentWorkspaceId: 'workspace', currentMessages: [],
        activeStreams: new Map(), activeRuns: [],
        locallyStoppedRunIds: new Set(), finishedRunIds: new Set(), pendingComposerSubmits: new Set(),
        pendingAttachments: [], submitSeq: 0, model: 'test', accessScope: 'workspace',
        confirmationPolicy: 'auto', pendingRunLaunch: null,
    };
    const nodes = new Map();
    const timers = new Map();
    const frames = [];
    const requests = [];
    const sandbox = {
        state, console, AbortController, Date, JSON, Map, Set,
        $: (id) => {
            if (!nodes.has(id)) nodes.set(id, { value: id === 'message-input' ? '优化住宅' : '',
                textContent: '', classList: { add() {}, remove() {}, toggle() {} } });
            return nodes.get(id);
        },
        t: (key) => key, window: { requestAnimationFrame: (fn) => frames.push(fn) },
        setInterval: (fn) => { const key = {}; timers.set(key, fn); return key; },
        clearInterval: (key) => timers.delete(key),
        renderMessages: (messages) => { state.currentMessages = messages; },
        api: async (url) => {
            requests.push(url);
            if (url.startsWith('/runs?')) return sandbox.listed || [];
            if (url === '/runs/run-1') {
                if (sandbox.apiError) throw new Error('offline');
                return run;
            }
            if (url === '/conversations/conv') {
                if (sandbox.beforeConversation) sandbox.beforeConversation();
                return final;
            }
            throw new Error(`unexpected API: ${url}`);
        },
        streamApi: async (_url, _body, onEvent, signal) => {
            onEvent({ event: 'run', run: { ...run, status: 'running', stage: 'thinking' } });
            onEvent({ event: 'reasoning', reasoning: '已有推理' });
            onEvent({ event: 'tool', tool: 'inspect', task_id: 'tool-1', status: 'success' });
            if (mode === 'done') {
                onEvent({ event: 'done', conversation: final, run_status: 'success' });
                return;
            }
            if (mode === 'eof') return;
            await new Promise((_resolve, reject) => signal.addEventListener('abort', () =>
                reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true }));
        },
        uploadAttachmentFiles: async () => [],
        hasPersistentRunPlaceholder: () => false,
        findToolEventIndex: () => -1,
    };
    for (const name of ['clearAttachmentUpload', 'mergeStreamGuidanceMessages', 'renderWorkspaces',
        'renderConversations', 'renderCurrentWorkspace', 'renderContextBar', 'upsertConversationSummary',
        'refreshComposerStateUnused', 'refreshTaskHistory', 'showToast']) sandbox[name] = () => {};
    vm.createContext(sandbox);
    vm.runInContext(functions, sandbox);
    return { sandbox, state, run, final, nodes, timers, frames, requests };
}

async function start(ctx) {
    const sent = ctx.sandbox.sendMessage({ preventDefault() {} });
    await new Promise(setImmediate);
    return { sent, stream: ctx.state.activeStreams.get('conv') };
}

test('丢失 done 且连接悬挂：后台终态恢复原文、保留过程并释放发送状态', async () => {
    const ctx = setup();
    const { sent, stream } = await start(ctx);
    await ctx.sandbox.refreshActiveRuns();
    await sent;
    for (const frame of ctx.frames) frame();
    assert.equal(ctx.state.activeStreams.size, 0);
    assert.equal(ctx.state.activeRuns.length, 0);
    assert.equal(ctx.state.isSending, false);
    assert.equal(ctx.timers.size, 0);
    assert.equal(ctx.state.currentMessages.at(-1).content, ctx.final.messages.at(-1).content);
    assert.equal(ctx.state.currentMessages.at(-1).metadata.reasoning, '已有推理');
    assert.equal(ctx.state.currentMessages.at(-1).metadata.tool_events.length, 1);
    assert.equal(stream.messages.at(-1).metadata.pending, undefined);
    assert.equal(ctx.nodes.get('send-btn').textContent, 'composer.send');
    assert(ctx.requests.every((url) => !url.includes('/actions')));
});

for (const [status, stage] of [['running', 'thinking'], ['waiting_confirmation', 'waiting_confirmation'],
    ['paused', 'paused'], ['created', 'created'], ['success', 'result']]) {
    test(`尚未封存的 ${status}/${stage} 不会被当成结束`, async () => {
        const ctx = setup();
        const { sent, stream } = await start(ctx);
        Object.assign(ctx.run, { status, stage });
        await ctx.sandbox.refreshActiveRuns();
        assert.equal(ctx.state.activeStreams.get('conv'), stream);
        assert.equal(stream.abortController.signal.aborted, false);
        stream.abortController.abort();
        await sent;
    });
}

test('正常 done 后旧轮询结果不会重新显示运行中', async () => {
    const ctx = setup('done');
    const { sent } = await start(ctx);
    await sent;
    ctx.sandbox.listed = [{ ...ctx.run, status: 'running', stage: 'thinking' }];
    await ctx.sandbox.refreshActiveRuns();
    assert.equal(ctx.state.activeRuns.length, 0);
    assert.equal(ctx.state.activeStreams.size, 0);
    assert.equal(ctx.timers.size, 0);
    assert.equal(ctx.state.currentMessages.at(-1).content, ctx.final.messages.at(-1).content);
});

test('收到 EOF 但没有 done 时仍核对后台终态', async () => {
    const ctx = setup('eof');
    const { sent } = await start(ctx);
    await sent;
    assert.equal(ctx.state.activeStreams.size, 0);
    assert.equal(ctx.state.currentMessages.at(-1).content, ctx.final.messages.at(-1).content);
    assert.equal(ctx.state.isSending, false);
});

test('查询期间已换成新流，旧流清理不能覆盖新流', async () => {
    const ctx = setup();
    const { sent, stream } = await start(ctx);
    const replacement = { runId: 'run-2', status: 'running', messages: [] };
    ctx.sandbox.beforeConversation = () => ctx.state.activeStreams.set('conv', replacement);
    await ctx.sandbox.refreshActiveRuns();
    assert.equal(ctx.state.activeStreams.get('conv'), replacement);
    assert.equal(stream.abortController.signal.aborted, false);
    stream.abortController.abort();
    await sent;
    assert.equal(ctx.state.activeStreams.get('conv'), replacement);
});

test('后台终态同步不会切换用户正在查看的对话', async () => {
    const ctx = setup();
    const { sent } = await start(ctx);
    ctx.state.currentConversationId = 'other';
    const visible = [{ role: 'user', content: '另一个对话' }];
    ctx.state.currentMessages = visible;
    await ctx.sandbox.refreshActiveRuns();
    await sent;
    assert.equal(ctx.state.currentConversationId, 'other');
    assert.equal(ctx.state.currentMessages, visible);
    assert.equal(ctx.state.activeStreams.size, 0);
});

test('查询失败不猜测执行结束', async () => {
    const ctx = setup();
    const { sent, stream } = await start(ctx);
    ctx.sandbox.apiError = true;
    await ctx.sandbox.refreshActiveRuns();
    assert.equal(ctx.state.activeStreams.get('conv'), stream);
    assert.equal(stream.abortController.signal.aborted, false);
    stream.abortController.abort();
    await sent;
});

for (const status of ['failure', 'partial', 'stopped', 'cancelled']) {
    test(`恢复 ${status} 终态保留模型原文`, async () => {
        const ctx = setup();
        const { sent, stream } = await start(ctx);
        ctx.run.status = status;
        ctx.final.messages.at(-1).content = '原始结果：' + status;
        await ctx.sandbox.refreshActiveRuns();
        await sent;
        assert.equal(stream.status, status);
        assert.equal(ctx.state.currentMessages.at(-1).content, '原始结果：' + status);
        assert.equal(ctx.state.activeStreams.size, 0);
    });
}
