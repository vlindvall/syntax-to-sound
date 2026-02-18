const statusLine = document.getElementById('statusLine');
const settingsStatus = document.getElementById('settingsStatus');
const messages = document.getElementById('messages');
const eventsBox = document.getElementById('eventsBox');
let traceList = document.getElementById('traceList');
const traceEntries = [];
let sessionId = null;

function logMessage(kind, text) {
  const el = document.createElement('div');
  el.className = `msg ${kind}`;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
}

function logEvent(text) {
  eventsBox.textContent += `${new Date().toLocaleTimeString()} ${text}\n`;
  eventsBox.scrollTop = eventsBox.scrollHeight;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

async function boot() {
  const data = await api('/api/runtime/boot', { method: 'POST' });
  sessionId = data.session_id;
  statusLine.textContent = `Status: ${data.status} (${sessionId})`;
  logMessage('system', `Boot: ${data.status}`);
  await loadLLMSettings();
}

async function stop() {
  await api('/api/runtime/stop', { method: 'POST' });
  logMessage('system', 'Clock cleared');
}

async function loadSong() {
  const path = document.getElementById('songPath').value;
  await api('/api/runtime/load-song', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
  logMessage('system', `Loaded: ${path}`);
}

async function sendPrompt() {
  if (!sessionId) await boot();
  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) return;
  const intent = document.getElementById('intentInput').value;
  logMessage('user', prompt);
  const requestBody = { session_id: sessionId, prompt, intent };
  const data = await callChatTurn('chat', requestBody);
  const result = formatTurnResult(data);
  logMessage('system', `${result} (${data.latency_ms}ms)`);
  logNormalizationInfo(data);
}

async function applyMixer() {
  if (!sessionId) await boot();
  const ampValue = Number(document.getElementById('p1_amp').value);
  const commands = [
    { op: 'player_set', player: 'p1', param: 'amp', value: ampValue },
    { op: 'player_set', player: 'p1', param: 'lpf', value: Number(document.getElementById('p1_lpf').value) },
    { op: 'player_set', player: 'p1', param: 'hpf', value: Number(document.getElementById('p1_hpf').value) },
    { op: 'player_set', player: 'p1', param: 'pan', value: Number(document.getElementById('p1_pan').value) },
  ];
  const mixerTurn = await callChatTurn('mixer', {
    session_id: sessionId,
    prompt: JSON.stringify(commands),
    intent: 'mix_fix',
  });
  logMessage('system', formatTurnResult(mixerTurn));
  logNormalizationInfo(mixerTurn);
  if (ampValue === 0) logMessage('system', 'P1 muted (amp=0)');
}

async function setBpm() {
  if (!sessionId) await boot();
  const bpm = Number(document.getElementById('bpmInput').value);
  const prompt = `Set bpm to ${bpm}`;
  const data = await callChatTurn('bpm', { session_id: sessionId, prompt, intent: 'edit' });
  logMessage('system', formatTurnResult(data));
  logNormalizationInfo(data);
}

function formatTurnResult(data) {
  if (data.validation?.valid && data.apply_status === 'applied') {
    return `Applied patch #${data.patch_id}`;
  }
  if (!data.validation?.valid) {
    const errors = (data.validation?.errors || []).join('; ') || 'unknown validation error';
    return `Rejected: ${errors}`;
  }
  if (data.apply_status === 'failed') {
    const errors = (data.validation?.errors || []).join('; ') || 'runtime apply failed';
    return `Apply failed: ${errors}`;
  }
  return `Patch skipped (#${data.patch_id})`;
}

function logNormalizationInfo(data) {
  if (!data.normalized) return;
  const notes = (data.normalization_notes || []).slice(0, 2).join(' | ');
  const suffix = data.normalization_notes?.length > 2 ? ' ...' : '';
  logMessage('system', `Repaired commands before apply: ${notes}${suffix}`);
}

async function callChatTurn(origin, requestBody) {
  const path = '/api/chat/turn';
  const startedAt = new Date().toISOString();
  try {
    const data = await api(path, {
      method: 'POST',
      body: JSON.stringify(requestBody),
    });
    addTraceEntry({
      origin,
      startedAt,
      path,
      requestBody,
      responseBody: data,
    });
    return data;
  } catch (err) {
    addTraceEntry({
      origin,
      startedAt,
      path,
      requestBody,
      error: err.message,
    });
    throw err;
  }
}

function addTraceEntry(entry) {
  traceEntries.unshift(entry);
  const list = ensureTraceList();
  if (!list) return;

  const details = document.createElement('details');
  details.className = 'trace-item';
  details.open = true;

  const summary = document.createElement('summary');
  summary.textContent = buildTraceSummary(entry);
  details.appendChild(summary);

  const content = document.createElement('div');
  content.className = 'trace-content';
  appendTraceStage(content, '1) User/Input', {
    origin: entry.origin,
    prompt: entry.requestBody.prompt,
    intent: entry.requestBody.intent,
    session_id: entry.requestBody.session_id,
    started_at: entry.startedAt,
  });
  appendTraceStage(content, '2) API Request Body', entry.requestBody);

  if (entry.responseBody) {
    appendTraceStage(content, '3) Model Output (raw commands)', entry.responseBody.commands || []);
    appendTraceStage(content, '4) Normalized Effective Commands', entry.responseBody.effective_commands || []);
    appendTraceStage(content, '5) Emitted Renardo Python', entry.responseBody.emitted_code || '');
    appendTraceStage(content, '6) Outcome', {
      patch_id: entry.responseBody.patch_id,
      model: entry.responseBody.model,
      apply_status: entry.responseBody.apply_status,
      validation: entry.responseBody.validation,
      normalized: entry.responseBody.normalized,
      normalization_notes: entry.responseBody.normalization_notes || [],
      latency_ms: entry.responseBody.latency_ms,
    });
  } else {
    appendTraceStage(content, '3) Error', { error: entry.error || 'Unknown error' });
  }

  details.appendChild(content);
  list.prepend(details);
}

function ensureTraceList() {
  if (traceList) return traceList;

  const chatPanel = document.querySelector('.panel.chat');
  if (!chatPanel) return null;

  let wrap = chatPanel.querySelector('.trace-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'trace-wrap';

    const title = document.createElement('h3');
    title.textContent = 'Command Trace';
    wrap.appendChild(title);

    traceList = document.createElement('div');
    traceList.id = 'traceList';
    traceList.className = 'trace-list';
    wrap.appendChild(traceList);

    const inputRow = chatPanel.querySelector('.row');
    if (inputRow) {
      chatPanel.insertBefore(wrap, inputRow);
    } else {
      chatPanel.appendChild(wrap);
    }
    return traceList;
  }

  traceList = wrap.querySelector('#traceList');
  if (!traceList) {
    traceList = document.createElement('div');
    traceList.id = 'traceList';
    traceList.className = 'trace-list';
    wrap.appendChild(traceList);
  }
  return traceList;
}

function traceToPlainText(entry) {
  const lines = [];
  lines.push(buildTraceSummary(entry));
  lines.push('1) User/Input');
  lines.push(formatPayload({
    origin: entry.origin,
    prompt: entry.requestBody.prompt,
    intent: entry.requestBody.intent,
    session_id: entry.requestBody.session_id,
    started_at: entry.startedAt,
  }));
  lines.push('2) API Request Body');
  lines.push(formatPayload(entry.requestBody));

  if (entry.responseBody) {
    lines.push('3) Model Output (raw commands)');
    lines.push(formatPayload(entry.responseBody.commands || []));
    lines.push('4) Normalized Effective Commands');
    lines.push(formatPayload(entry.responseBody.effective_commands || []));
    lines.push('5) Emitted Renardo Python');
    lines.push(formatPayload(entry.responseBody.emitted_code || ''));
    lines.push('6) Outcome');
    lines.push(formatPayload({
      patch_id: entry.responseBody.patch_id,
      model: entry.responseBody.model,
      apply_status: entry.responseBody.apply_status,
      validation: entry.responseBody.validation,
      normalized: entry.responseBody.normalized,
      normalization_notes: entry.responseBody.normalization_notes || [],
      latency_ms: entry.responseBody.latency_ms,
    }));
  } else {
    lines.push('3) Error');
    lines.push(formatPayload({ error: entry.error || 'Unknown error' }));
  }

  return lines.join('\n');
}

async function copyText(text) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    logMessage('system', 'Copied trace to clipboard');
    return;
  }
  const tmp = document.createElement('textarea');
  tmp.value = text;
  document.body.appendChild(tmp);
  tmp.select();
  document.execCommand('copy');
  document.body.removeChild(tmp);
  logMessage('system', 'Copied trace to clipboard');
}

async function loadLLMSettings() {
  const payload = await api('/api/settings/llm');
  document.getElementById('llmBackend').value = payload.backend || 'auto';
  document.getElementById('llmModel').value = payload.model || '';
  document.getElementById('codexCommand').value = payload.codex_command || '';
  document.getElementById('codexModel').value = payload.codex_model || '';
  document.getElementById('llmApiKey').value = '';
  updateSettingsDisclosure(payload.backend || 'auto');
  const keyInfo = payload.has_api_key ? `saved ${payload.api_key_hint || ''}` : 'not set';
  setSettingsStatus(`LLM settings loaded: backend=${payload.backend}, model=${payload.model}, key=${keyInfo}`);
}

async function saveLLMSettings() {
  const apiKeyInput = document.getElementById('llmApiKey').value.trim();
  const request = {
    backend: document.getElementById('llmBackend').value,
    model: document.getElementById('llmModel').value.trim(),
    codex_command: document.getElementById('codexCommand').value.trim(),
    codex_model: document.getElementById('codexModel').value.trim(),
  };
  if (apiKeyInput.length > 0) {
    request.api_key = apiKeyInput;
  }

  const payload = await api('/api/settings/llm', {
    method: 'POST',
    body: JSON.stringify(request),
  });
  document.getElementById('llmApiKey').value = '';
  updateSettingsDisclosure(payload.backend || 'auto');
  const keyInfo = payload.has_api_key ? `saved ${payload.api_key_hint || ''}` : 'not set';
  setSettingsStatus(`LLM settings saved: backend=${payload.backend}, model=${payload.model}, key=${keyInfo}`);
  logMessage('system', `LLM settings updated (${payload.backend})`);
}

function setSettingsStatus(text) {
  if (settingsStatus) settingsStatus.textContent = text;
}

function updateSettingsDisclosure(backend) {
  const apiKeyRow = document.getElementById('apiKeyRow');
  const advanced = document.getElementById('advancedSettings');
  if (!apiKeyRow || !advanced) return;

  if (backend === 'fallback-local') {
    apiKeyRow.classList.add('hidden');
    advanced.classList.add('hidden');
    return;
  }
  if (backend === 'openai-api') {
    apiKeyRow.classList.remove('hidden');
    advanced.classList.add('hidden');
    return;
  }
  if (backend === 'codex-cli') {
    apiKeyRow.classList.add('hidden');
    advanced.classList.remove('hidden');
    advanced.open = true;
    return;
  }
  // auto: show key and keep codex controls optional via collapsed advanced details
  apiKeyRow.classList.remove('hidden');
  advanced.classList.remove('hidden');
  advanced.open = false;
}

function appendTraceStage(parent, title, payload) {
  const label = document.createElement('div');
  label.className = 'trace-stage-title';
  label.textContent = title;
  parent.appendChild(label);

  const pre = document.createElement('pre');
  pre.textContent = formatPayload(payload);
  parent.appendChild(pre);
}

function buildTraceSummary(entry) {
  const stamp = new Date().toLocaleTimeString();
  if (!entry.responseBody) {
    return `[${stamp}] ${entry.origin} -> failed`;
  }
  const response = entry.responseBody;
  return `[${stamp}] ${entry.origin} -> patch #${response.patch_id} (${response.apply_status})`;
}

function formatPayload(payload) {
  if (typeof payload === 'string') {
    return payload.length ? payload : '(empty)';
  }
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

async function undoLast() {
  if (!sessionId) return;
  const data = await api('/api/patch/undo', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });
  logMessage('system', `Undo ok for patch ${data.reverted_patch_id}`);
}

function connectEvents() {
  const stream = new EventSource('/api/events/stream');
  stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      logEvent(`[${payload.source}] ${payload.message}`);
    } catch {
      logEvent(event.data);
    }
  };
  stream.onerror = () => logEvent('event stream disconnected');
}

document.getElementById('bootBtn').onclick = () => boot().catch((e) => logMessage('system', e.message));
document.getElementById('stopBtn').onclick = () => stop().catch((e) => logMessage('system', e.message));
document.getElementById('loadBtn').onclick = () => loadSong().catch((e) => logMessage('system', e.message));
document.getElementById('sendBtn').onclick = () => sendPrompt().catch((e) => logMessage('system', e.message));
document.getElementById('applyMixerBtn').onclick = () => applyMixer().catch((e) => logMessage('system', e.message));
document.getElementById('bpmBtn').onclick = () => setBpm().catch((e) => logMessage('system', e.message));
document.getElementById('undoBtn').onclick = () => undoLast().catch((e) => logMessage('system', e.message));
document.getElementById('refreshSettingsBtn').onclick = () =>
  loadLLMSettings().catch((e) => logMessage('system', e.message));
document.getElementById('saveSettingsBtn').onclick = () =>
  saveLLMSettings().catch((e) => logMessage('system', e.message));
document.getElementById('llmBackend').onchange = (e) =>
  updateSettingsDisclosure(e.target.value);
const clearTraceBtn = document.getElementById('clearTraceBtn');
if (clearTraceBtn) {
  clearTraceBtn.onclick = () => {
    const list = ensureTraceList();
    if (list) list.textContent = '';
    traceEntries.length = 0;
  };
}
const copyLastTraceBtn = document.getElementById('copyLastTraceBtn');
if (copyLastTraceBtn) {
  copyLastTraceBtn.onclick = () => {
    if (!traceEntries.length) {
      logMessage('system', 'No trace entries to copy');
      return;
    }
    copyText(traceToPlainText(traceEntries[0])).catch((e) => logMessage('system', e.message));
  };
}
const copyAllTraceBtn = document.getElementById('copyAllTraceBtn');
if (copyAllTraceBtn) {
  copyAllTraceBtn.onclick = () => {
    if (!traceEntries.length) {
      logMessage('system', 'No trace entries to copy');
      return;
    }
    const payload = traceEntries.map(traceToPlainText).join('\n\n');
    copyText(payload).catch((e) => logMessage('system', e.message));
  };
}

connectEvents();
ensureTraceList();
boot().catch((e) => logMessage('system', e.message));
