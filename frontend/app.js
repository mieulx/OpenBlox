let curId = null, sending = false, abortController = null;
let editingIndex = null;
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

function stopThinking() {
  abortFetch();
  clearTimeout(_sendTimer);
  document.querySelectorAll('.think').forEach(el => el.remove());
  sending = false;
  document.getElementById('send-btn').disabled = false;
  document.getElementById('chat-input').focus();
  showError('Stopped by user', 'warn');
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
    loadSession(curId);
    populateModels(md.models || [], md.free_models || []);
    const cfg = await api('/api/config').catch(() => ({}));
    if (cfg.model) {
      $('#model-picker').value = cfg.model;
      $('#s-model').value = cfg.model;
    }
    if (cfg.user_context) $('#s-context').value = cfg.user_context;
  } catch (e) { toast('Failed to load: ' + e.message, 'err'); }
}
document.addEventListener('DOMContentLoaded', init);

function populateModels(all) {
  const picker = $('#model-picker');
  const sModel = $('#s-model');
  picker.innerHTML = '';
  sModel.innerHTML = '';
  for (const m of all) {
    const label = m.tier ? m.tier + ' \u2014 ' + m.id : m.id;
    const o1 = document.createElement('option');
    o1.value = m.id; o1.textContent = label;
    picker.appendChild(o1);
    sModel.appendChild(o1.cloneNode(true));
  }
}

const MODEL_LABELS = {
  'kilo-auto/free': 'Auto',
  'nvidia/nemotron-3-super-120b-a12b:free': 'Apex',
  'arcee-ai/trinity-large-thinking:free': 'Rover',
};

async function switchModel(id) {
  $('#s-model').value = id;
  await saveConf();
  toast('Switched to ' + (MODEL_LABELS[id] || id), 'ok');
}

// ─── Sessions ───
function renderSessions(list) {
  const el = document.getElementById('session-list');
  el.innerHTML = list.map(s =>
    `<div class="session-item ${s.id === curId ? 'active' : ''}"
         onclick="switchSession('${s.id}')"
         ondblclick="openRename('${s.id}')">
      <span>${esc(s.title)}</span>
      <button class="del" onclick="event.stopPropagation(); delSession('${s.id}')">&times;</button>
    </div>`
  ).join('');
}

async function switchSession(id) {
  curId = id;
  cancelEdit();
  await loadSession(id);
  refreshSessions();
}

async function loadSession(id) {
  const m = document.getElementById('messages');
  if (!id) { m.innerHTML = welcome(); return; }
  try {
    const d = await api('/api/sessions/' + id);
    m.innerHTML = d.messages.map((msg, i) => renderMsg(msg.role, msg.content, i)).join('');
    scrollDown();
  } catch { m.innerHTML = welcome(); }
}

async function newChat() {
  const d = await api('/api/sessions', { method: 'POST' });
  curId = d.id;
  cancelEdit();
  document.getElementById('messages').innerHTML = welcome();
  refreshSessions();
}

async function delSession(id) {
  const list = (await api('/api/sessions')).sessions;
  if (list.length <= 1) { toast('Cannot delete last chat', 'err'); return; }
  await api('/api/sessions/' + id, { method: 'DELETE' });
  const d = await api('/api/sessions');
  curId = d.active_id;
  cancelEdit();
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

  editingIndex = index;
  document.getElementById('chat-input').value = textEl.textContent;
  resizeInput(document.getElementById('chat-input'));
  document.getElementById('input-bar').classList.add('editing');
  document.getElementById('chat-input').focus();
  scrollDown();
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

  // Interrupt previous request if still sending
  if (sending) {
    abortFetch();
    clearTimeout(_sendTimer);
    // Remove old thinking indicator
    const oldThink = document.querySelector('.think');
    if (oldThink) oldThink.remove();
    sending = false;
    document.getElementById('send-btn').disabled = false;
  }

  inp.value = ''; inp.style.height = 'auto';
  sending = true;
  abortController = new AbortController();
  clearError();
  document.getElementById('input-bar').classList.remove('editing');

  const msgs = document.getElementById('messages');
  const w = msgs.querySelector('.welcome');
  if (w) msgs.innerHTML = '';

  const editIdx = editingIndex;

  if (editingIndex === null) {
    msgs.insertAdjacentHTML('beforeend', renderMsg('user', text, -1));
  }
  editingIndex = null;

  const tid = 't-' + Date.now();
  msgs.insertAdjacentHTML('beforeend',
    `<div id="${tid}" class="think"><span>Thinking</span><span class="d"><span></span><span></span><span></span></span><button class="stop-btn" onclick="stopThinking()">Stop</button></div>`
  );
  scrollDown();
  document.getElementById('send-btn').disabled = true;

  const dev = document.getElementById('dev-mode').checked;
  let timedOut = false;
  _sendTimer = setTimeout(() => {
    timedOut = true;
    document.getElementById(tid)?.remove();
    showError('Request timed out after ' + (TIMEOUT_MS/1000) + 's.', 'err');
    msgs.insertAdjacentHTML('beforeend', renderMsg('assistant', '_Request timed out._', -1));
    scrollDown();
    sending = false;
    document.getElementById('send-btn').disabled = false;
  }, TIMEOUT_MS);

  try {
    const body = { message: text, session_id: curId, dev_mode: dev };
    if (editIdx !== null) body.edit_index = editIdx;

    const data = await api('/api/chat', {
      method: 'POST',
      body: JSON.stringify(body),
      signal: abortController.signal,
    });

    clearTimeout(_sendTimer);
    if (timedOut) return;
    if (abortController.signal.aborted) return;

    curId = data.session.id;
    document.getElementById(tid)?.remove();

    if (dev && data.dev_chunks.length) {
      showDev(data.dev_chunks);
    } else {
      hideDev();
    }

    const sess = await api('/api/sessions/' + curId);
    msgs.innerHTML = sess.messages.map((msg, i) => renderMsg(msg.role, msg.content, i)).join('');
    scrollDown();
    refreshSessions();
  } catch (e) {
    clearTimeout(_sendTimer);
    if (timedOut || abortController?.signal.aborted) return;
    document.getElementById(tid)?.remove();
    const errMsg = e.message.includes('Failed to fetch')
      ? 'Cannot reach server.'
      : e.message.includes('timed out')
      ? 'Request timed out.'
      : e.message;
    showError(errMsg, 'err');
    msgs.insertAdjacentHTML('beforeend', renderMsg('assistant', '_Error: ' + esc(errMsg) + '_', -1));
    scrollDown();
  }

  sending = false;
  document.getElementById('send-btn').disabled = false;
  inp.focus();
}

function renderMsg(role, text, index) {
  const isUser = role === 'user';
  const label = isUser ? 'You' : 'Assistant';
  const lc = isUser ? 'user-label' : '';
  const body = isUser ? esc(text) : fmt(text);
  const click = isUser ? ` onclick="editMessage(${index})" title="Click to edit"` : '';
  return `
    <div class="msg-group">
      <div class="msg-label ${lc}">${label}</div>
      <div class="msg ${isUser ? 'user' : 'bot'}"${click}>${body}</div>
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
    if (/^\s*(?:\d+[\.\)]|[-*])\s+/.test(lines[i]) || /^\s*[-*]\s*\[[ x]\]/.test(lines[i])) {
      const items = [];
      const startIdx = i;
      while (i < lines.length && (/^\s*(?:\d+[\.\)]|[-*])\s+/.test(lines[i]) || /^\s*[-*]\s*\[[ x]\]/.test(lines[i]))) {
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

function fmt(t) {
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
function showDev(chunks) {
  const p = document.getElementById('dev-panel');
  document.getElementById('dev-content').textContent =
    chunks.map(c => `\u2500\u2500 ${c.heading} \u2500\u2500\n${c.text.slice(0, 300)}`).join('\n\n');
  p.classList.remove('hidden');
}
function hideDev() { document.getElementById('dev-panel').classList.add('hidden'); }
function toggleDev() { if (!document.getElementById('dev-mode').checked) hideDev(); }

// ─── Welcome ───
function welcome() {
  return `
    <div class="welcome">
      <svg class="bolt-big" viewBox="0 0 24 24">
        <path d="M13 2L4 14h5v8l9-12h-5z" fill="currentColor"/>
      </svg>
      <h1>Kilo Roblox Studio Helper</h1>
      <p>Ask anything about Roblox Studio. Toggle Dev to see raw documentation.</p>
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
    document.getElementById('s-temp').value = c.temperature;
    document.getElementById('s-temp-val').textContent = c.temperature;
    if (c.user_context) document.getElementById('s-context').value = c.user_context;
    if (c.max_chunks) document.getElementById('s-chunks').value = c.max_chunks;
    if (c.chunk_size) document.getElementById('s-size').value = c.chunk_size;
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
  const body = { model, temperature: temp, max_chunks: chunks, chunk_size: size };
  if (key) body.api_key = key;
  if (ctx !== undefined) body.user_context = ctx;
  await api('/api/config', { method: 'POST', body: JSON.stringify(body) });
  document.getElementById('model-picker').value = model;
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
  if (panel.classList.contains('hidden')) {
    panel.classList.remove('hidden');
    btn.classList.add('active');
    await refreshTools();
  } else {
    panel.classList.add('hidden');
    btn.classList.remove('active');
  }
}

let _mcpActive = false;

function updateMCPIndicator() {
  const el = document.getElementById('mcp-indicator');
  if (el) {
    el.classList.toggle('hidden', !_mcpActive);
  }
}

async function refreshTools() {
  try {
    const d = await api('/api/tools?session_id=' + (curId || ''));
    const el = document.getElementById('tools-list');
    _mcpActive = false;
    el.innerHTML = d.tools.map(t => {
      if (t.enabled && t.mcp_count) _mcpActive = true;
      return `
        <div class="tool-item">
          <div class="tool-info">
            <div class="tool-name">${esc(t.name)}</div>
            ${t.enabled && t.mcp_count ? `<span class="tool-status">${t.mcp_count} tools ready</span>` : ''}
          </div>
          <div class="tool-switch ${t.enabled ? 'on' : ''}" onclick="toggleTool('${t.id}')"></div>
        </div>`;
    }).join('');
    updateMCPIndicator();
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
