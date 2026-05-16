let curId = null, sending = false, abortController = null;
let editingIndex = null;
let _contextPct = 0;
let _agentMode = false;
let _agentPanelCollapsed = false;
let _agentStripCollapsed = false;
let _agentTrace = [];
let _agentConfig = { subagent_model: '', max_subagents: 2, chain_thought: false };
let _devState = { metrics: null };
let _liveMsgEl = null;
let _permReqId = null;
let _permPollTimer = null;
const TIMEOUT_MS = 120000;

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

async function api(p, o = {}) {
  const r = await fetch(p, {
    headers: { 'Content-Type': 'application/json', ...o.headers },
    ...o,
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(e.error || r.statusText);
  }
  return r.json();
}

function abortFetch() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

function collapseLongMessages() {
  document.querySelectorAll('.msg.bot').forEach(el => {
    if (el.scrollHeight > 500 && !el.dataset.collapsed) {
      el.dataset.collapsed = '1';
      el.style.maxHeight = '400px';
      el.style.overflow = 'hidden';
      el.style.position = 'relative';
      const btn = document.createElement('button');
      btn.textContent = 'Show all';
      btn.className = 'expand-btn';
      btn.onclick = function() {
        el.style.maxHeight = '';
        el.style.overflow = '';
        btn.remove();
      };
      el.parentElement.appendChild(btn);
    }
  });
}

function updateContextBar(sess) {
  const el = document.getElementById('ctx-bar');
  if (!el || !sess) { return; }
  _contextPct = sess.context_pct !== undefined ? sess.context_pct : 0;
  const used = sess.context_tokens || 0;
  const limit = sess.context_limit || 262144;
  el.innerHTML = `<span class="ctx-fill" style="width:${Math.min(_contextPct, 100)}%"></span><span class="ctx-text">${_contextPct}% (${(used/1000).toFixed(0)}K / ${(limit/1000).toFixed(0)}K)</span>`;
  el.className = 'ctx-bar' + (_contextPct >= 80 ? ' ctx-high' : _contextPct >= 60 ? ' ctx-warn' : '');
}

function updateSendBtn() {
  const btn = document.getElementById('send-btn');
  if (sending) {
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M6 6h12v12H6z" fill="currentColor"/></svg>';
    btn.onclick = stopThinking;
    btn.classList.add('stop');
  } else {
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" fill="currentColor"/></svg>';
    btn.onclick = send;
    btn.classList.remove('stop');
  }
}

function stopThinking() {
  abortFetch();
  clearTimeout(_sendTimer);
  removeThinkFold();
  sending = false;
  document.getElementById('send-btn').disabled = false;
  updateSendBtn();
  document.getElementById('chat-input').focus();
  showError('Stopped by user', 'warn');
}

function toggleAgentMode() {
  _agentMode = !_agentMode;
  const btn = document.getElementById('agent-mode-btn');
  if (btn) btn.classList.toggle('active', _agentMode);
  const title = document.getElementById('agent-plan-title');
  if (title && !_agentTrace.length) title.textContent = _agentMode ? 'Agent Run Ready' : 'Execution Plan';
}

function toggleAgentPanelBody() {
  _agentPanelCollapsed = !_agentPanelCollapsed;
  const panel = document.getElementById('agent-sidebar');
  if (panel) panel.classList.toggle('collapsed', _agentPanelCollapsed);
}

function resetAgentTrace() {
  _agentTrace = [];
  const trace = document.getElementById('agent-trace');
  if (trace) trace.innerHTML = '';
  const side = document.getElementById('agent-sidebar');
  if (side) side.classList.add('hidden');
}

function prettyMsg(msg) {
  if (!msg || typeof msg !== 'string') return '';
  const trimmed = msg.trim();
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      const obj = JSON.parse(trimmed);
      if (typeof obj === 'object' && obj !== null) {
        return flattenObj(obj);
      }
    } catch {}
  }
  return msg;
}

function flattenObj(obj, indent = '') {
  if (Array.isArray(obj)) {
    return obj.map((item, i) => {
      if (typeof item === 'object' && item !== null) {
        return `${indent}[${i}]\n${flattenObj(item, indent + '  ')}`;
      }
      return `${indent}- ${item}`;
    }).join('\n');
  }
  if (typeof obj === 'object' && obj !== null) {
    return Object.entries(obj).map(([k, v]) => {
      if (typeof v === 'object' && v !== null) {
        return `${indent}${k}:\n${flattenObj(v, indent + '  ')}`;
      }
      return `${indent}${k}: ${v}`;
    }).join('\n');
  }
  return `${indent}${obj}`;
}

function addAgentTrace(agent, stage, message) {
  _agentTrace.push({ agent, stage, message });
  const trace = document.getElementById('agent-trace');
  const panel = document.getElementById('agent-sidebar');
  if (!trace || !panel) return;
  panel.classList.remove('hidden');
  trace.innerHTML = _agentTrace.map(item => {
    const formatted = prettyMsg(item.message || '');
    return `
    <div class="agent-trace-item">
      <div class="agent-trace-head">
        <span class="agent-trace-agent">${esc(item.agent || 'Agent')}</span>
        <span class="agent-trace-stage">${esc(item.stage || 'update')}</span>
      </div>
      <div class="agent-trace-text">${esc(formatted)}</div>
    </div>`;
  }).join('');
}

function renderAgentPlan(plan) {
  const panel = document.getElementById('agent-todo-strip');
  const side = document.getElementById('agent-sidebar');
  const itemsEl = document.getElementById('agent-plan-items');
  const progressEl = document.getElementById('agent-plan-progress');
  const titleEl = document.getElementById('agent-plan-title');
  if (!panel || !itemsEl || !progressEl || !titleEl) return;
  const items = Array.isArray(plan) ? plan : [];
  if (!items.length && !_agentTrace.length) {
    panel.classList.add('hidden');
    if (side) side.classList.add('hidden');
    itemsEl.innerHTML = '';
    progressEl.textContent = '0 of 0 done';
    titleEl.textContent = 'Execution Plan';
    return;
  }
  panel.classList.remove('hidden');
  panel.classList.toggle('expanded', items.length > 6);
  panel.classList.toggle('collapsed', _agentStripCollapsed);
  const done = items.filter(item => item.done).length;
  progressEl.textContent = `${done} of ${items.length} done`;
  titleEl.textContent = _agentMode ? 'Agent Execution Plan' : 'Execution Plan';

  let html = items.map((item, i) => `
    <div class="agent-plan-item ${item.done ? 'done' : ''}" onclick="event.stopPropagation();togglePlanItem(${i})" title="${item.done ? 'Mark incomplete' : 'Mark complete'}">
      <span class="agent-plan-check"></span>
      <span class="agent-plan-text agent-plan-text-overflow" title="${esc(item.text || '')}">${esc(item.text || '')}</span>
    </div>
  `).join('');

  itemsEl.innerHTML = html;
}

async function togglePlanItem(index) {
  if (!curId) return;
  const sess = await api(`/api/sessions/${curId}`).catch(() => null);
  if (!sess) return;
  const items = sess.agent_plan || [];
  if (index < 0 || index >= items.length) return;
  const done = !items[index].done;
  const res = await api(`/api/sessions/${curId}/plan`, {
    method: 'PATCH',
    body: JSON.stringify({ index, done }),
  }).catch(() => null);
  if (res && res.agent_plan) {
    renderAgentPlan(res.agent_plan);
  }
}

function toggleAgentStrip() {
  _agentStripCollapsed = !_agentStripCollapsed;
  const panel = document.getElementById('agent-todo-strip');
  if (panel) panel.classList.toggle('collapsed', _agentStripCollapsed);
}

function updateDevPanel() {
  const panel = document.getElementById('dev-panel');
  const content = document.getElementById('dev-content');
  if (!panel || !content) return;
  const hasMetrics = !!_devState.metrics;
  if (!hasMetrics) {
    panel.classList.add('hidden');
    content.innerHTML = '';
    return;
  }
  panel.classList.remove('hidden');
  const m = _devState.metrics;
  const cards = [
    ['Model', m.model || '-'],
    ['TTFT', m.ttft_ms ? `${m.ttft_ms} ms` : '-'],
    ['Total', m.total_ms ? `${m.total_ms} ms` : '-'],
    ['TPS', m.tps_est ? `${m.tps_est}` : '0'],
    ['Tokens', m.output_tokens_est || 0],
    ['Rounds', m.rounds || 0],
    ['Tools', m.tool_calls || 0],
  ];
  content.innerHTML = `<div class="dev-metrics">${cards.map(([label, value]) => `
    <div class="dev-metric">
      <div class="dev-metric-label">${esc(String(label))}</div>
      <div class="dev-metric-value">${esc(String(value))}</div>
    </div>
  `).join('')}</div>`;
}

// ─── Init ───
async function init() {
  try {
    const [sd, md] = await Promise.all([
      api('/api/sessions'),
      api('/api/models').catch(() => ({ models: [], free_models: [] })),
    ]);
    curId = sd.active_id;
    renderSessions(sd.sessions);
    if (curId) {
      const sess = await api('/api/sessions/' + curId).catch(() => null);
      if (sess && sess.messages && sess.messages.length) {
        document.getElementById('messages').innerHTML = sess.messages.map((msg, i) => renderMsg(msg.role, msg.content, i, msg.timestamp)).join('');
        // Restore agent logs on page load
        if (sess.agent_logs && sess.agent_logs.length) {
          _agentTrace = sess.agent_logs;
          const trace = document.getElementById('agent-trace');
          const panel = document.getElementById('agent-sidebar');
          if (trace && panel) {
            panel.classList.remove('hidden');
            trace.innerHTML = _agentTrace.map(item => {
              const formatted = prettyMsg(item.message || '');
              return `<div class="agent-trace-item"><div class="agent-trace-head"><span class="agent-trace-agent">${esc(item.agent || 'Agent')}</span><span class="agent-trace-stage">${esc(item.stage || 'update')}</span></div><div class="agent-trace-text">${esc(formatted)}</div></div>`;
            }).join('');
          }
        }
        renderAgentPlan(sess.agent_plan || []);
      } else {
        showWelcome();
        renderAgentPlan([]);
      }
    } else {
      showWelcome();
      renderAgentPlan([]);
    }
    populateModels(md.models || [], md.free_models || []);
    const cfg = await api('/api/config').catch(() => ({}));
    if (cfg.model) {
      $('#model-picker').value = cfg.model;
      $('#s-model').value = cfg.model;
    }
    if (cfg.user_context) $('#s-context').value = cfg.user_context;
    if (cfg.dev_mode !== undefined) {
      const dEl = document.getElementById('s-dev-mode');
      if (dEl) dEl.checked = cfg.dev_mode;
      toggleDev();
    }
    const ver = await api('/api/version').catch(() => ({ version: '' }));
    const vEl = document.getElementById('version-display');
    if (vEl && ver.version) vEl.textContent = 'v' + ver.version;
  } catch (e) { toast('Failed to load: ' + e.message, 'err'); }
}
document.addEventListener('DOMContentLoaded', init);

function populateModels(all) {
  const picker = $('#model-picker');
  const sModel = $('#s-model');
  const subModel = $('#s-subagent-model');
  const dev = (document.getElementById('s-dev-mode') || {}).checked || false;
  _ALL_MODELS.length = 0;
  _ALL_MODELS.push(...all);
  picker.innerHTML = '';
  sModel.innerHTML = '';
  if (subModel && !subModel.options.length) {
    subModel.innerHTML = '<option value="">Same as main</option>';
  }
  for (const m of all) {
    const label = dev && m.id ? m.tier + ' \u2014 ' + m.id : m.tier;
    const o1 = document.createElement('option');
    o1.value = m.id; o1.textContent = label;
    picker.appendChild(o1);
    sModel.appendChild(o1.cloneNode(true));
    if (subModel) {
      const o2 = document.createElement('option');
      o2.value = m.id; o2.textContent = m.tier + ' \u2014 ' + m.id;
      subModel.appendChild(o2);
    }
  }
}

const MODEL_LABELS = {
  'nvidia/nemotron-3-super-120b-a12b:free': 'Apex 0.9',
};
const _ALL_MODELS = []; // populated by populateModels

async function switchModel(id) {
  $('#s-model').value = id;
  await saveConf();
  // Save model to current session
  if (curId) {
    await api('/api/sessions/' + curId + '/model', {
      method: 'PATCH',
      body: JSON.stringify({ title: id }),
    }).catch(() => {});
  }
  toast('Switched to ' + (MODEL_LABELS[id] || id), 'ok');
}

// ─── Sessions ───
function renderSessions(list) {
  const el = document.getElementById('session-list');
  const now = Date.now();
  const day = 86400000;
  const groups = [
    { label: 'Recent', max: day, sessions: [] },
    { label: 'Week ago', max: 7 * day, sessions: [] },
    { label: 'Month ago', max: 30 * day, sessions: [] },
    { label: 'Long time ago', max: Infinity, sessions: [] },
  ];
  list.forEach(s => {
    const ts = (s.updated || s.created || 0) * 1000;
    const age = now - ts;
    for (const g of groups) {
      if (age < g.max) { g.sessions.push(s); break; }
    }
  });
  el.innerHTML = groups.map(g => {
    if (!g.sessions.length) return '';
    return `<div class="session-group-label">${g.label}</div>` +
      g.sessions.map(s =>
        `<div class="session-item ${s.id === curId ? 'active' : ''}"
             onclick="switchSession('${s.id}')"
             ondblclick="openRename('${s.id}')">
          <span title="${esc(s.title)}">${esc(s.title.length > 24 ? s.title.slice(0, 24) + '..' : s.title)}</span>
          <button class="del" onclick="event.stopPropagation(); delSession('${s.id}')">&times;</button>
        </div>`
      ).join('');
  }).join('');
}

async function switchSession(id) {
  curId = id;
  cancelEdit();
  await loadSession(id);
  refreshSessions();
}

async function loadSession(id) {
  const m = document.getElementById('messages');
  if (!id) { showWelcome(); return; }
  try {
    const d = await api('/api/sessions/' + id);
    m.innerHTML = d.messages.map((msg, i) => renderMsg(msg.role, msg.content, i, msg.timestamp)).join('');
    collapseLongMessages();
    // Restore per-chat model
    if (d.model) {
      $('#model-picker').value = d.model;
      $('#s-model').value = d.model;
    }
    // Update context display
    updateContextBar(d);
    // Reset all agent state before restoring
    resetAgentTrace();
    _agentTrace = [];
    // Restore persisted agent logs
    if (d.agent_logs && d.agent_logs.length) {
      _agentTrace = d.agent_logs;
      const trace = document.getElementById('agent-trace');
      const panel = document.getElementById('agent-sidebar');
      if (trace && panel) {
        panel.classList.remove('hidden');
        trace.innerHTML = _agentTrace.map(item => {
          const formatted = prettyMsg(item.message || '');
          return `
          <div class="agent-trace-item">
            <div class="agent-trace-head">
              <span class="agent-trace-agent">${esc(item.agent || 'Agent')}</span>
              <span class="agent-trace-stage">${esc(item.stage || 'update')}</span>
            </div>
            <div class="agent-trace-text">${esc(formatted)}</div>
          </div>`;
        }).join('');
      }
    }
    renderAgentPlan(d.agent_plan || []);
    _devState = { metrics: null };
    updateDevPanel();
    scrollDown();
  } catch { showWelcome(); }
}

async function newChat() {
  const d = await api('/api/sessions', { method: 'POST' });
  curId = d.id;
  // Save current model to new session
  const model = $('#model-picker').value;
  if (model) {
    await api('/api/sessions/' + curId + '/model', {
      method: 'PATCH', body: JSON.stringify({ title: model }),
    }).catch(() => {});
  }
  cancelEdit();
  resetAgentTrace();
  renderAgentPlan([]);
  showWelcome();
  refreshSessions();
}

async function delSession(id) {
  const list = (await api('/api/sessions')).sessions;
  if (list.length <= 1) { toast('Cannot delete last chat', 'err'); return; }
  await api('/api/sessions/' + id, { method: 'DELETE' });
  const d = await api('/api/sessions');
  curId = d.active_id;
  cancelEdit();
  resetAgentTrace();
  renderAgentPlan([]);
  renderSessions(d.sessions);
  loadSession(curId);
}

async function refreshSessions() {
  const d = await api('/api/sessions');
  renderSessions(d.sessions);
}

// ─── Rename ───
let renameTarget = null;

function openRename(id) {
  renameTarget = id;
  const overlay = document.getElementById('rename-overlay');
  const input = document.getElementById('rename-input');
  overlay.classList.remove('hidden');
  input.value = '';
  input.focus();
}

function closeRename(e) {
  if (e && e.target !== document.getElementById('rename-overlay')) return;
  document.getElementById('rename-overlay').classList.add('hidden');
}

async function confirmRename() {
  const title = document.getElementById('rename-input').value.trim();
  if (!title || !renameTarget) return;
  await api('/api/sessions/' + renameTarget + '/rename', {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
  document.getElementById('rename-overlay').classList.add('hidden');
  refreshSessions();
  toast('Renamed to "' + title + '"', 'ok');
}

// ─── Export ───
async function exportChat() {
  if (!curId) { toast('No chat to export', 'err'); return; }
  window.open('/api/sessions/' + curId + '/export', '_blank');
}

// ─── Edit & Resend ───
function editMessage(index) {
  const msgs = document.getElementById('messages');
  const groups = msgs.querySelectorAll('.msg-group');
  if (index < 0 || index >= groups.length) return;
  const group = groups[index];
  const textEl = group.querySelector('.msg.user');
  if (!textEl) return;
  // Prevent editing messages that start with /
  if (textEl.textContent.trim().startsWith('/')) return;

  editingIndex = index;
  document.getElementById('chat-input').value = textEl.textContent;
  resizeInput(document.getElementById('chat-input'));
  document.getElementById('input-bar').classList.add('editing');
  document.getElementById('chat-input').focus();
  scrollDown();
}

let _thinkingTid = null;

function setThinkStatus(text) {
  if (!_thinkingTid) return;
  const el = document.getElementById('tf-status-' + _thinkingTid);
  if (el) el.textContent = text;
}

function addThinkStep(type, text) {
  if (!_thinkingTid) return;
  const steps = document.getElementById('tf-steps-' + _thinkingTid);
  if (!steps) return;
  const cls = type === 'tool' ? 'accent' : type === 'output' ? 'dim' : '';
  const label = type === 'tool' ? '▸ ' : '';
  steps.innerHTML += `<div class="tf-step"><span class="${cls}">${label}${esc(text)}</span></div>`;
}

function removeThinkFold() {
  if (!_thinkingTid) return;
  const el = document.getElementById(_thinkingTid);
  if (el) el.remove();
  _thinkingTid = null;
}

function toggleThinkFold(tid) {
  const el = document.getElementById(tid);
  if (el) el.classList.toggle('open');
}

function cancelEdit() {
  editingIndex = null;
  document.getElementById('input-bar').classList.remove('editing');
}

// ─── Chat ───
let _sendTimer = null;

async function send() {
  const inp = document.getElementById('chat-input');
  const text = inp.value.trim();
  if (!text) return;

  // Auto-create chat if no session
  if (!curId) {
    const newSess = await api('/api/sessions', { method: 'POST' });
    curId = newSess.id;
    await refreshSessions();
  }

  // Block sending while AI is generating — use Stop button instead
  if (sending) {
    return;
  }

  // Handle /commands
  if (text.startsWith('/')) {
    if (text === '/compact') {
      sending = false;
      const d = await api('/api/compact', { method: 'POST', body: JSON.stringify({ session_id: curId }) });
      if (d.ok) {
        updateContextBar(d.session || d);
        toast('Context compacted!', 'ok');
        await loadSession(curId);
      } else {
        toast(d.note || 'Failed to compact', 'err');
      }
      updateSendBtn();
      return;
    }
    toast('Unknown command: ' + text, 'err');
    updateSendBtn();
    return;
  }

  // Block sending if context is over 70%
  if (_contextPct >= 70) {
    showError('Context is ' + _contextPct + '% full. Type /compact to free up space before continuing.', 'warn');
    updateSendBtn();
    return;
  }

  inp.value = ''; inp.style.height = 'auto';
  sending = true;
  abortController = new AbortController();
  if (_agentMode) {
    resetAgentTrace();
    renderAgentPlan([]);
    addAgentTrace('Planner', 'queued', 'Preparing agent plan.');
  }
  _devState = { metrics: null };
  updateDevPanel();
  clearError();
  document.getElementById('input-bar').classList.remove('editing');
  updateSendBtn();

  const msgs = document.getElementById('messages');
  const w = msgs.querySelector('.welcome');
  if (w) msgs.innerHTML = '';

  const editIdx = editingIndex;

  if (editingIndex === null) {
    msgs.insertAdjacentHTML('beforeend', renderMsg('user', text, -1));
  }
  editingIndex = null;

  _thinkingTid = 'think-' + Date.now();
  const liveMsgId = 'live-' + Date.now();
  const msgGroup = document.createElement('div');
  msgGroup.className = 'msg-group';
  msgGroup.id = liveMsgId;
  msgGroup.innerHTML = `
    <div class="msg-label">Assistant <span class="msg-time">now</span></div>
    <div class="msg bot" id="${liveMsgId}-body">
      <span class="stream-cursor" id="${liveMsgId}-cursor"></span>
    </div>
    <div id="${_thinkingTid}" class="think-fold">
      <div class="tf-head" onclick="toggleThinkFold('${_thinkingTid}')">
        <span class="tf-arrow">▶</span>
        <span class="tf-status" id="tf-status-${_thinkingTid}">Thinking</span>
        <span class="tf-dots"><span></span><span></span><span></span></span>
      </div>
      <div class="tf-body" id="tf-body-${_thinkingTid}">
        <div class="tf-steps" id="tf-steps-${_thinkingTid}"></div>
      </div>
    </div>
  `;
  msgs.appendChild(msgGroup);
  _liveMsgEl = msgGroup;
  scrollDown();
  document.getElementById('send-btn').disabled = false;
  updateSendBtn();

  const dev = (document.getElementById('s-dev-mode') || {}).checked || false;
  let timedOut = false;
  _sendTimer = setTimeout(() => {
    timedOut = true;
    if (_thinkingTid) {
      const el = document.getElementById('tf-status-' + _thinkingTid);
      if (el) el.textContent = 'Still thinking...';
    }
    showError('Taking longer than expected...', 'warn');
    setTimeout(() => {
      if (_thinkingTid) {
        const el = document.getElementById('tf-status-' + _thinkingTid);
        if (el) el.textContent = 'Still thinking, really';
      }
    }, 60000);
  }, TIMEOUT_MS);

  let accumulatedContent = '';

  try {
    const body = { message: text, session_id: curId, dev_mode: dev, agent_mode: _agentMode, subagent_model: _agentConfig.subagent_model, max_subagents: _agentConfig.max_subagents, chain_thought: _agentConfig.chain_thought };
    if (editIdx !== null) body.edit_index = editIdx;

    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: abortController.signal,
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    startPermPoll();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === 'thinking') {
            if (accumulatedContent) accumulatedContent += '\n\n';
            accumulatedContent += event.content;
            const bodyEl = document.getElementById(liveMsgId + '-body');
            if (bodyEl) {
              bodyEl.innerHTML = fmt(accumulatedContent) + '<span class="stream-cursor"></span>';
              scrollDown();
            }
            addThinkStep('text', event.content.slice(0, 80));
          } else if (event.type === 'tool') {
            addThinkStep('tool', event.tool + ' through ' + event.integration);
            if (_agentMode) addAgentTrace(event.integration || 'Tool', 'tool', event.tool);
          } else if (event.type === 'tool_declined') {
            addThinkStep('output', '✗ ' + (event.tool || 'Tool') + ' declined');
            if (_agentMode) addAgentTrace('Tool', 'declined', event.tool);
          } else if (event.type === 'tool_output') {
            const out = event.output;
            if (out) addThinkStep('output', out.slice(0, 120));
            if (_agentMode && out) addAgentTrace('Tool Output', 'result', out.slice(0, 240));
          } else if (event.type === 'metric') {
            if (dev) {
              _devState.metrics = { ...(_devState.metrics || {}), ...event.metric };
              updateDevPanel();
            }
          } else if (event.type === 'metrics') {
            if (dev) {
              _devState.metrics = event.metrics || null;
              updateDevPanel();
            }
          } else if (event.type === 'agent_plan') {
            renderAgentPlan(event.session_plan || []);
            addAgentTrace('Planner', 'plan', event.plan?.summary || 'Plan ready.');
          } else if (event.type === 'agent_plan_update') {
            renderAgentPlan(event.session_plan || []);
          } else if (event.type === 'agent_working') {
            const workEl = document.getElementById('agent-working');
            if (workEl) workEl.classList.remove('hidden');
          } else if (event.type === 'agent_status') {
            addAgentTrace(event.agent || 'Agent', event.stage || 'status', event.message || '');
          } else if (event.type === 'permission_needed') {
            // Show permission dialog immediately via SSE (more reliable than polling)
            _permReqId = event.request_id;
            document.getElementById('perm-tool-val').textContent = event.tool || 'unknown';
            document.getElementById('perm-overlay').classList.remove('hidden');
          } else if (event.type === 'permission_wait') {
            addThinkStep('text', 'Waiting for permission: ' + (event.tool || 'tool') + '...');
          } else if (event.type === 'done') {
            const workEl = document.getElementById('agent-working');
            if (workEl) workEl.classList.add('hidden');
            removeThinkFold();
            _liveMsgEl = null;
            accumulatedContent = event.content || '(no response)';
          } else if (event.type === 'session') {
            clearTimeout(_sendTimer);
            if (abortController.signal.aborted) return;
            _liveMsgEl = null;
            const sess = event.session;
            msgs.innerHTML = sess.messages.map((msg, i) => renderMsg(msg.role, msg.content, i, msg.timestamp)).join('');
            collapseLongMessages();
            updateContextBar(sess);
            renderAgentPlan(sess.agent_plan || []);
            // Restore agent logs after streaming completes
            if (sess.agent_logs && sess.agent_logs.length) {
              _agentTrace = sess.agent_logs;
              const trace = document.getElementById('agent-trace');
              const panel = document.getElementById('agent-sidebar');
              if (trace && panel) {
                panel.classList.remove('hidden');
                trace.innerHTML = _agentTrace.map(item => {
                  const formatted = prettyMsg(item.message || '');
                  return `<div class="agent-trace-item"><div class="agent-trace-head"><span class="agent-trace-agent">${esc(item.agent || 'Agent')}</span><span class="agent-trace-stage">${esc(item.stage || 'update')}</span></div><div class="agent-trace-text">${esc(formatted)}</div></div>`;
                }).join('');
              }
            }
            scrollDown();
            refreshSessions();
          } else if (event.type === 'error') {
            clearTimeout(_sendTimer);
            removeThinkFold();
            showError(event.content, 'err');
            msgs.insertAdjacentHTML('beforeend', renderMsg('assistant', '_Error: ' + esc(event.content) + '_', -1));
            scrollDown();
          }
        } catch (e) { /* skip malformed events */ }
      }
    }
  } catch (e) {
    clearTimeout(_sendTimer);
    stopPermPoll();
    if (abortController?.signal.aborted) { updateSendBtn(); return; }
    removeThinkFold();
    const errMsg = e.message;
    showError(errMsg, 'err');
    msgs.insertAdjacentHTML('beforeend', renderMsg('assistant', '_Error: ' + esc(errMsg) + '_', -1));
    scrollDown();
  }

  stopPermPoll();
  sending = false;
  document.getElementById('send-btn').disabled = false;
  updateSendBtn();
  inp.focus();
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function renderMsg(role, text, index, ts) {
  const isUser = role === 'user';
  const label = isUser ? 'You' : 'Assistant';
  const lc = isUser ? 'user-label' : '';
  const body = isUser ? esc(text) : fmt(text);
  const time = fmtTime(ts);
  const pen = isUser ? `<button class="pen-btn" onclick="editMessage(${index})" title="Edit message"><svg viewBox="0 0 24 24" width="13" height="13"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" fill="currentColor"/></svg></button>` : '';
  return `
    <div class="msg-group">
      <div class="msg-label ${lc}">${label}${time ? ` <span class="msg-time">${time}</span>` : ''}</div>
      <div class="msg ${isUser ? 'user' : 'bot'}">${body}</div>
      ${pen}
    </div>
  `;
}

const LUA_KEYWORDS = new Set([
  'and','break','do','else','elseif','end','false','for','function',
  'goto','if','in','local','nil','not','or','repeat','return','then',
  'true','until','while'
]);

const ROBLOX_TYPES = new Set([
  'Instance','Vector3','Vector2','CFrame','Color3','ColorSequence',
  'NumberRange','NumberSequence','Ray','RaycastResult','BrickColor',
  'UDim','UDim2','Rect','Region3','Region3int16','Enum','Axes',
  'Faces','PathWaypoint','Random','DateTime','TweenInfo',
  'AnimationTrack','Sound','Part','BasePart','Model','Script',
  'LocalScript','ModuleScript','Folder','Tool','Player','Players',
  'Workspace','Lighting','ReplicatedStorage','ServerStorage',
  'ServerScriptService','StarterGui','StarterPack','StarterPlayer',
  'HttpService','TweenService','RunService','UserInputService',
  'ContextActionService','InsertService','CollectionService',
  'ContentProvider','MarketplaceService','Debris','MaterialService',
  'PhysicsService','Teams','TextService','VirtualInputManager'
]);

function highlightLua(code) {
  let escaped = esc(code);
  const lines = escaped.split('\n');
  let result = '';
  for (let li = 0; li < lines.length; li++) {
    if (li > 0) result += '\n';
    const line = lines[li];
    const tokens = [];
    let i = 0;
    while (i < line.length) {
      if (line.slice(i).startsWith('--[[')) {
        let end = line.indexOf(']]', i + 4);
        if (end === -1) end = line.length; else end += 2;
        tokens.push({ t: 'comment', v: line.slice(i, end) }); i = end; continue;
      }
      if (line.slice(i).startsWith('--')) {
        tokens.push({ t: 'comment', v: line.slice(i) }); i = line.length; continue;
      }
      if (line[i] === '"') {
        let end = i + 1;
        while (end < line.length) { if (line[end] === '\\') end += 2; else if (line[end] === '"') { end++; break; } else end++; }
        tokens.push({ t: 'string', v: line.slice(i, end) }); i = end; continue;
      }
      if (line[i] === "'") {
        let end = i + 1;
        while (end < line.length) { if (line[end] === '\\') end += 2; else if (line[end] === "'") { end++; break; } else end++; }
        tokens.push({ t: 'string', v: line.slice(i, end) }); i = end; continue;
      }
      if (/[a-zA-Z_]/.test(line[i])) {
        let end = i;
        while (end < line.length && /[a-zA-Z0-9_]/.test(line[end])) end++;
        const word = line.slice(i, end);
        if (LUA_KEYWORDS.has(word)) tokens.push({ t: 'keyword', v: word });
        else if (ROBLOX_TYPES.has(word)) tokens.push({ t: 'builtin', v: word });
        else if (word[0] === word[0].toUpperCase() && word[0] !== word[0].toLowerCase() && !word.includes('_'))
          tokens.push({ t: 'type', v: word });
        else if (end < line.length && line[end] === '(') tokens.push({ t: 'func', v: word });
        else tokens.push({ t: 'text', v: word });
        i = end; continue;
      }
      if (/[0-9]/.test(line[i])) {
        let end = i;
        while (end < line.length && /[0-9.eExXa-fA-F_]/.test(line[end])) end++;
        tokens.push({ t: 'num', v: line.slice(i, end) }); i = end; continue;
      }
      if (/\s/.test(line[i])) {
        let end = i;
        while (end < line.length && /\s/.test(line[end])) end++;
        tokens.push({ t: 'space', v: line.slice(i, end) }); i = end; continue;
      }
      tokens.push({ t: 'op', v: line[i] }); i++;
    }
    for (const tok of tokens) {
      switch (tok.t) {
        case 'comment': result += `<span class="hl-comment">${tok.v}</span>`; break;
        case 'string': result += `<span class="hl-string">${tok.v}</span>`; break;
        case 'keyword': result += `<span class="hl-keyword">${tok.v}</span>`; break;
        case 'builtin': result += `<span class="hl-builtin">${tok.v}</span>`; break;
        case 'type': result += `<span class="hl-type">${tok.v}</span>`; break;
        case 'func': result += `<span class="hl-function">${tok.v}</span>`; break;
        case 'num': result += `<span class="hl-number">${tok.v}</span>`; break;
        default: result += tok.v;
      }
    }
  }
  return result;
}

let _uid = 0;
let _checklistId = 0;

function renderChecklist(text) {
  const lines = text.split('\n');
  const result = [];
  let i = 0;
  while (i < lines.length) {
    const stepRe = /^\s*(?:\[DONE\]\s*)?(?:\d+[\.\)]|[-*])\s+/;
    const taskRe = /^\s*[-*]\s*\[[ x]\]/;
    if (stepRe.test(lines[i]) || taskRe.test(lines[i])) {
      const items = [];
      const startIdx = i;
      while (i < lines.length && (stepRe.test(lines[i]) || taskRe.test(lines[i]))) {
        const raw = lines[i];
        let checked = false;
        let stepText = raw;
        if (/^\s*[-*]\s*\[[ x]\]/.test(raw)) {
          checked = /\[x\]/.test(raw);
          stepText = raw.replace(/^\s*[-*]\s*\[[ x]\]\s*/, '');
        } else {
          checked = /\[DONE\]|\[done\]|✓/.test(raw);
          stepText = raw.replace(/^\s*(?:\d+[\.\)]|[-*])\s*/, '');
          stepText = stepText.replace(/\s*\[DONE\]|\s*\[done\]|\s*✓/g, '');
        }
        if (stepText.trim()) {
          items.push({ text: stepText.trim(), checked });
        }
        i++;
      }
      if (items.length >= 2) {
        const cid = 'cl-' + (_checklistId++);
        let progress = items.filter(it => it.checked).length;
        let total = items.length;
        let pct = Math.round((progress / total) * 100);
        let html = `<div class="checklist" id="${cid}"><div class="cl-progress"><div class="cl-bar" style="width:${pct}%"></div><span>${progress}/${total}</span></div><div class="cl-items">`;
        items.forEach((item, idx) => {
          html += `<label class="cl-item ${item.checked ? 'done' : ''}"><input type="checkbox" ${item.checked ? 'checked' : ''} onchange="toggleChecklistItem(this, '${cid}')"><span class="cl-check"></span><span class="cl-text">${esc(item.text)}</span></label>`;
        });
        html += '</div></div>';
        result.push(html);
        continue;
      }
      i = startIdx;
    }
    result.push(lines[i]);
    i++;
  }
  return result.join('\n');
}

function toggleChecklistItem(cb, cid) {
  const label = cb.parentElement;
  label.classList.toggle('done', cb.checked);
  const cl = document.getElementById(cid);
  if (!cl) return;
  const items = cl.querySelectorAll('.cl-item');
  const done = cl.querySelectorAll('.cl-item.done').length;
  const total = items.length;
  const pct = Math.round((done / total) * 100);
  const bar = cl.querySelector('.cl-bar');
  const span = cl.querySelector('.cl-progress span');
  if (bar) bar.style.width = pct + '%';
  if (span) span.textContent = done + '/' + total;
}



function autoWrapLua(t) {
  // Skip if already inside a fenced code block
  if (/```[\s\S]*```/.test(t)) return t;
  const lines = t.split('\n');
  let codeStart = -1;
  let codeEnd = -1;
  let lastEnd = -1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    // Detect start of Lua code
    if (codeStart === -1 && (
      /^local\s/.test(line) ||
      /^function\s/.test(line) ||
      /^for\s/.test(line) ||
      /^while\s/.test(line) ||
      /^if\s/.test(line) ||
      /^repeat\s/.test(line) ||
      /^do\s/.test(line) ||
      /^::/.test(line) ||
      line.includes('Instance.new') ||
      line.includes('= {}') ||
      /\.new\(/.test(line)
    )) {
      codeStart = i;
    }
    // Track all ends
    if (/^end\b/.test(line) || line === 'end') {
      lastEnd = i;
    }
  }

  // If we found code start and at least one end, wrap everything between
  if (codeStart >= 0 && lastEnd >= codeStart) {
    // Check if this is substantial code (at least 3 lines or contains function/keywords)
    const codeLines = lines.slice(codeStart, lastEnd + 1);
    const codeText = codeLines.join('\n');
    if (codeLines.length >= 3 || /function|for |while |if .+ then/.test(codeText)) {
      const before = lines.slice(0, codeStart).join('\n');
      const after = lines.slice(lastEnd + 1).join('\n');
      const id = 'c-' + (_uid++);
      const highlighted = highlightLua(codeText);
      const rawAttr = codeText.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '&#10;');
      const wrapped = `<div class="pre-wrap"><pre id="${id}" data-code="${rawAttr}">${highlighted}</pre><button class="copy-btn" onclick="copyCode('${id}', this)">Copy</button></div>`;
      return before + (before ? '\n\n' : '') + wrapped + (after ? '\n\n' + after : '');
    }
  }
  return t;
}

function fmt(t) {
  t = autoWrapLua(t);
  t = t.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const id = 'c-' + (_uid++);
    const highlighted = (lang === 'lua' || lang === 'luau' || lang === '')
      ? highlightLua(code) : esc(code);
    const rawAttr = code.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '&#10;');
    return `<div class="pre-wrap"><pre id="${id}" data-code="${rawAttr}">${highlighted}</pre><button class="copy-btn" onclick="copyCode('${id}', this)">Copy</button></div>`;
  });
  t = renderChecklist(t);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)/g, '<em>$1</em>');
  t = t.replace(/(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)/g, '<em>$1</em>');
  t = t.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  t = t.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  t = t.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  t = t.replace(/^---+\s*$/gm, '<hr>');
  t = t.replace(/\n/g, '<br>');
  return t;
}

function esc(t) {
  const d = document.createElement('div');
  d.textContent = t;
  return d.innerHTML;
}

function copyCode(id, btn) {
  const pre = document.getElementById(id);
  if (!pre) return;
  let text = pre.getAttribute('data-code');
  if (!text) text = pre.textContent;
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.style.left = '0';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch {}
  document.body.removeChild(ta);
  btn.textContent = 'Copied!';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
}

// ─── Error Bar ───
function showError(msg, type) {
  const bar = document.getElementById('error-bar');
  bar.textContent = msg;
  bar.className = type;
  bar.classList.remove('hidden');
}
function clearError() {
  document.getElementById('error-bar').classList.add('hidden');
}

// ─── Dev Panel ───
let _devPanelOpen = true;

function toggleDevPanel() {
  _devPanelOpen = !_devPanelOpen;
  const panel = document.getElementById('dev-panel');
  const content = document.getElementById('dev-content');
  if (panel) panel.classList.toggle('collapsed', !_devPanelOpen);
  if (content) content.style.display = _devPanelOpen ? '' : 'none';
}

function hideDev() {
  _devState = { metrics: null };
  updateDevPanel();
}
function toggleDev() {
  const cb = document.getElementById('s-dev-mode');
  const dev = cb ? cb.checked : false;
  if (!dev) hideDev();
  _devPanelOpen = dev;
  [ $('#model-picker'), $('#s-model') ].forEach(sel => {
    for (let i = 0; i < sel.options.length; i++) {
      const m = _ALL_MODELS.find(x => x.id === sel.options[i].value);
      if (m) sel.options[i].textContent = dev ? m.tier + ' \u2014 ' + m.id : m.tier;
    }
  });
}

// ─── Permission System ───
function startPermPoll() {
  stopPermPoll();
  _permPollTimer = setInterval(async () => {
    try {
      const res = await fetch('/api/permission/pending').then(r => r.json());
      if (res.pending && res.request_id) {
        _permReqId = res.request_id;
        document.getElementById('perm-tool-val').textContent = res.tool_name || 'unknown';
        const warn = document.getElementById('perm-asset-warn');
        if (warn) warn.classList.toggle('hidden', !res.is_asset);
        document.getElementById('perm-overlay').classList.remove('hidden');
      }
    } catch {}
  }, 800);
}
function stopPermPoll() {
  if (_permPollTimer) { clearInterval(_permPollTimer); _permPollTimer = null; }
}
async function permRespond(decision) {
  document.getElementById('perm-overlay').classList.add('hidden');
  if (_permReqId) {
    const body = { request_id: _permReqId, decision, tool_name: document.getElementById('perm-tool-val').textContent };
    await fetch('/api/permission/respond', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }).catch(() => {});
    _permReqId = null;
  }
}
function closePerm(e) {
  if (e && e.target && e.target.id === 'perm-overlay') document.getElementById('perm-overlay').classList.add('hidden');
}
async function clearPermCache() {
  await fetch('/api/permission/clear', { method: 'POST' }).catch(() => {});
  const el = document.getElementById('s-perm-status');
  if (el) { el.textContent = 'Cleared!'; setTimeout(() => el.textContent = '', 2000); }
}

// Allowed commands (always-permitted MCP tools)
let _allowedTools = [];

async function loadMcpToolNames() {
  try {
    const d = await api('/api/tools/mcp-names');
    return d.tools || [];
  } catch { return []; }
}

function renderAllowedToolsCheckboxes(tools, allowed) {
  const container = document.getElementById('s-allowed-tools-container');
  if (!container) return;
  if (!tools.length) {
    container.innerHTML = '<div style="padding:10px;font-size:11px;color:var(--text3);text-align:center">No MCP tools available. Enable Roblox Integration first.</div>';
    return;
  }
  container.innerHTML = tools.map(t => {
    const checked = allowed.includes(t);
    return `
      <label class="allowed-tool-item">
        <input type="checkbox" value="${esc(t)}" ${checked ? 'checked' : ''} onchange="onAllowedToolToggle(this)">
        <span class="allowed-tool-check"></span>
        <span class="allowed-tool-label">${esc(t)}</span>
      </label>`;
  }).join('');
}

function onAllowedToolToggle(cb) {
  const val = cb.value;
  if (cb.checked) {
    if (!_allowedTools.includes(val)) _allowedTools.push(val);
  } else {
    _allowedTools = _allowedTools.filter(t => t !== val);
  }
}

function selectAllAllowedTools() {
  const container = document.getElementById('s-allowed-tools-container');
  if (!container) return;
  const cbs = container.querySelectorAll('input[type="checkbox"]');
  cbs.forEach(cb => { cb.checked = true; });
  _allowedTools = Array.from(cbs).map(cb => cb.value);
}

function clearAllowedTools() {
  const container = document.getElementById('s-allowed-tools-container');
  if (!container) return;
  const cbs = container.querySelectorAll('input[type="checkbox"]');
  cbs.forEach(cb => { cb.checked = false; });
  _allowedTools = [];
}

// ─── Welcome ───
function showWelcome() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = `
    <div class="welcome">
      <img src="/assets/gradient.png" class="bolt-big" alt="OpenBlox">
      <h1>OpenBlox</h1>
      <p>Roblox Studio AI assistant.</p>
    </div>
  `;
}

function welcome() {
  return `
    <div class="welcome">
      <img src="/assets/gradient.png" class="bolt-big" alt="OpenBlox">
      <h1>OpenBlox</h1>
      <p>Roblox Studio AI assistant.</p>
    </div>
  `;
}

// ─── Settings ───
async function openSettings() {
  document.getElementById('modal-overlay').classList.remove('hidden');
  switchTab('api');
  try {
    const [c, md] = await Promise.all([
      api('/api/config'),
      api('/api/models').catch(() => ({ models: [] })),
    ]);
    if (!document.getElementById('s-model').options.length) populateModels(md.models || []);
    if (c.model) {
      document.getElementById('s-model').value = c.model;
      document.getElementById('model-picker').value = c.model;
    }
    // Subagent model select (same models but separate)
    const subSel = document.getElementById('s-subagent-model');
    if (subSel && !subSel.options.length) {
      subSel.innerHTML = '<option value="">Same as main</option>';
      for (const m of md.models || []) {
        const o = document.createElement('option');
        o.value = m.id; o.textContent = m.tier + ' \u2014 ' + m.id;
        subSel.appendChild(o);
      }
    }
    if (subSel && c.subagent_model) subSel.value = c.subagent_model;

    document.getElementById('s-temp').value = c.temperature;
    document.getElementById('s-temp-val').textContent = c.temperature;
    if (c.user_context) document.getElementById('s-context').value = c.user_context;
    if (c.max_chunks) document.getElementById('s-chunks').value = c.max_chunks;
    if (c.chunk_size) document.getElementById('s-size').value = c.chunk_size;
    if (c.max_subagents !== undefined) document.getElementById('s-max-subagents').value = c.max_subagents;
    const cotEl = document.getElementById('s-chain-thought');
    if (cotEl && c.chain_thought !== undefined) cotEl.checked = c.chain_thought;
    _agentConfig.subagent_model = c.subagent_model || '';
    _agentConfig.max_subagents = c.max_subagents || 2;
    _agentConfig.chain_thought = c.chain_thought || false;

    // Dev mode
    const devEl = document.getElementById('s-dev-mode');
    if (devEl && c.dev_mode !== undefined) devEl.checked = c.dev_mode;
    // Permissions
    const permEl = document.getElementById('s-perm-enabled');
    if (permEl && c.permissions_enabled !== undefined) permEl.checked = c.permissions_enabled;
    // Allowed tools
    _allowedTools = c.allowed_tools || [];
    const mcpTools = await loadMcpToolNames();
    renderAllowedToolsCheckboxes(mcpTools, _allowedTools);
  } catch {}
  try {
    const d = await api('/api/websites');
    document.getElementById('s-sites').innerHTML =
      d.websites.map(w =>
        `<div class="site-row"><span class="dot ${w.enabled ? 'on' : 'off'}"></span><span>${esc(w.name)}</span><span style="color:var(--text3);font-size:11px;margin-left:auto">${w.extractor_type}</span></div>`
      ).join('');
  } catch {}
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.add('hidden');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(e); closeRename(e); cancelEdit(); }
});

function switchTab(name) {
  $$('.tab').forEach(t => t.classList.remove('active'));
  $$('.tab-pane').forEach(t => t.classList.remove('active'));
  document.querySelector(`.tab[data-tab="${name}"]`).classList.add('active');
  document.getElementById('tp-' + name).classList.add('active');
}

function syncTemp(v) { document.getElementById('s-temp-val').textContent = v; }

async function saveConf() {
  const key = document.getElementById('s-apikey').value.trim();
  const model = document.getElementById('s-model').value.trim();
  const temp = parseFloat(document.getElementById('s-temp').value);
  const ctx = document.getElementById('s-context').value.trim();
  const chunks = parseInt(document.getElementById('s-chunks').value) || 8;
  const size = parseInt(document.getElementById('s-size').value) || 1500;
  const subModel = document.getElementById('s-subagent-model').value.trim();
  const maxSub = parseInt(document.getElementById('s-max-subagents').value) || 2;
  const chainThought = document.getElementById('s-chain-thought').checked;
  const devMode = document.getElementById('s-dev-mode').checked;
  const permEnabled = document.getElementById('s-perm-enabled').checked;
  const body = { model, temperature: temp, max_chunks: chunks, chunk_size: size, subagent_model: subModel, max_subagents: maxSub, chain_thought: chainThought, dev_mode: devMode, permissions_enabled: permEnabled, allowed_tools: _allowedTools };
  if (key) body.api_key = key;
  if (ctx !== undefined) body.user_context = ctx;
  await api('/api/config', { method: 'POST', body: JSON.stringify(body) });
  document.getElementById('model-picker').value = model;
  _agentConfig.subagent_model = subModel;
  _agentConfig.max_subagents = maxSub;
  _agentConfig.chain_thought = chainThought;
  // Apply dev mode
  toggleDev();
  const el = document.getElementById('s-save-status');
  el.textContent = 'Saved!';
  setTimeout(() => el.textContent = '', 2000);
  toast('Settings saved', 'ok');
}

async function testConn() {
  const key = document.getElementById('s-apikey').value.trim();
  const model = document.getElementById('s-model').value.trim();
  const el = document.getElementById('s-test-result');
  if (!key) { el.textContent = 'Enter a key first'; return; }
  el.textContent = 'Testing...';
  try {
    await api('/api/config', { method: 'POST', body: JSON.stringify({ api_key: key, model }) });
    const s = await api('/api/status');
    el.textContent = s.configured ? 'Connected!' : 'Failed';
    el.style.color = s.configured ? 'var(--cyan)' : '#ef4444';
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    el.style.color = '#ef4444';
  }
}

// ─── Utils ───
function resizeInput(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function scrollDown() {
  requestAnimationFrame(() => {
    document.getElementById('chat-view').scrollTop = 1e9;
  });
}

function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2500);
}

// ─── Tools ───
async function toggleToolsPanel() {
  const panel = document.getElementById('tools-panel');
  const btn = document.getElementById('tools-btn');
  if (!panel.classList.contains('open')) {
    panel.classList.add('open');
    btn.classList.add('active');
    await refreshTools();
  } else {
    panel.classList.remove('open');
    btn.classList.remove('active');
  }
}

async function refreshTools() {
  try {
    const d = await api('/api/tools?session_id=' + (curId || ''));
    const el = document.getElementById('tools-list');
    el.innerHTML = d.tools.map(t => {
      return `
        <div class="tool-item">
          <div class="tool-info">
            <div class="tool-name">${esc(t.name)}</div>
            ${t.enabled && t.mcp_count ? `<span class="tool-status">${t.mcp_count} tools ready</span>` : ''}
          </div>
          <div class="tool-switch ${t.enabled ? 'on' : ''}" onclick="toggleTool('${t.id}')"></div>
        </div>`;
    }).join('');
  } catch {}
}

async function toggleTool(id) {
  const d = await api('/api/tools/toggle', { method: 'POST', body: JSON.stringify({ tool_id: id, session_id: curId }) });
  await refreshTools();
  if (d.message) toast(d.message, d.ok ? 'ok' : 'err');
  else toast('Tool toggled', 'ok');
}

// ─── Keyboard ───
document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  if (e.key === 'Escape') cancelEdit();
});
