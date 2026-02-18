const dom = {
  statusLine: document.getElementById('statusLine'),
  settingsStatus: document.getElementById('settingsStatus'),
  messages: document.getElementById('messages'),
  activityLog: document.getElementById('activityLog'),
  eventsBox: document.getElementById('eventsBox'),
  runtimeState: document.getElementById('runtimeState'),
  sessionState: document.getElementById('sessionState'),
  eventsState: document.getElementById('eventsState'),
  traceList: document.getElementById('traceList'),
  troubleshootCard: document.getElementById('troubleshootCard'),
  troubleshootSummary: document.getElementById('troubleshootSummary'),
  troubleshootBudget: document.getElementById('troubleshootBudget'),
  troubleshootBtn: document.getElementById('troubleshootBtn'),
  applyFixBtn: document.getElementById('applyFixBtn'),
  dismissFixBtn: document.getElementById('dismissFixBtn'),
};

const uiState = {
  sessionId: null,
  runtime: 'idle',
  sse: 'connecting',
  troubleshootLimit: 3,
  troubleshootUsed: 0,
  failedTurn: null,
  repairedCommands: null,
};

const traceEntries = [];

function setRuntimeState(nextRuntime) {
  uiState.runtime = nextRuntime;
  renderStatus();
}

function setSseState(nextSse) {
  uiState.sse = nextSse;
  renderStatus();
}

function setSessionId(sessionId) {
  uiState.sessionId = sessionId;
  renderStatus();
}

function renderStatus() {
  if (dom.runtimeState) dom.runtimeState.textContent = uiState.runtime;
  if (dom.sessionState) dom.sessionState.textContent = uiState.sessionId ? uiState.sessionId.slice(0, 8) : 'n/a';
  if (dom.eventsState) dom.eventsState.textContent = uiState.sse;
  if (dom.statusLine) {
    const suffix = uiState.sessionId ? ` (${uiState.sessionId})` : '';
    dom.statusLine.textContent = `Status: ${uiState.runtime}${suffix}`;
  }
}

function appendLog(container, kind, text) {
  if (!container) return;
  const el = document.createElement('div');
  el.className = `msg ${kind}`;
  el.textContent = text;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

function logMessage(kind, text) {
  appendLog(dom.messages, kind, text);
  appendLog(dom.activityLog, kind, text);
}

function logEvent(text) {
  if (!dom.eventsBox) return;
  dom.eventsBox.textContent += `${new Date().toLocaleTimeString()} ${text}\n`;
  dom.eventsBox.scrollTop = dom.eventsBox.scrollHeight;
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
  setRuntimeState('booting');
  const data = await api('/api/runtime/boot', { method: 'POST' });
  setSessionId(data.session_id);
  setRuntimeState(data.status);
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

async function sendPrompt(promptOverride = '', intentOverride = '') {
  if (!uiState.sessionId) await boot();
  const promptInput = document.getElementById('promptInput');
  const prompt = (promptOverride || promptInput.value).trim();
  if (!prompt) return;
  const intent = intentOverride || document.getElementById('intentInput').value;

  logMessage('user', prompt);
  const requestBody = { session_id: uiState.sessionId, prompt, intent };
  const data = await callChatTurn('chat', requestBody);
  const result = formatTurnResult(data);
  logMessage('system', `${result} (${data.latency_ms}ms)`);
  logNormalizationInfo(data);
  handleTurnFailureState(data, requestBody);

  if (!promptOverride) {
    promptInput.value = '';
  }
}

async function sendQuickPrompt(prompt) {
  const intent = prompt.toLowerCase().includes('new scene') ? 'new_scene' : 'edit';
  await sendPrompt(prompt, intent);
}

async function applyMixer() {
  if (!uiState.sessionId) await boot();
  const ampValue = Number(document.getElementById('p1_amp').value);
  const commands = [
    { op: 'player_set', player: 'p1', param: 'amp', value: ampValue },
    { op: 'player_set', player: 'p1', param: 'lpf', value: Number(document.getElementById('p1_lpf').value) },
    { op: 'player_set', player: 'p1', param: 'hpf', value: Number(document.getElementById('p1_hpf').value) },
    { op: 'player_set', player: 'p1', param: 'pan', value: Number(document.getElementById('p1_pan').value) },
  ];
  const mixerTurn = await callChatTurn('mixer', {
    session_id: uiState.sessionId,
    prompt: JSON.stringify(commands),
    intent: 'mix_fix',
  });
  logMessage('system', formatTurnResult(mixerTurn));
  logNormalizationInfo(mixerTurn);
  hideTroubleshootCard();
  if (ampValue === 0) logMessage('system', 'P1 muted (amp=0)');
}

async function setBpm() {
  if (!uiState.sessionId) await boot();
  const bpm = Number(document.getElementById('bpmInput').value);
  const prompt = `Set bpm to ${bpm}`;
  const data = await callChatTurn('bpm', { session_id: uiState.sessionId, prompt, intent: 'edit' });
  logMessage('system', formatTurnResult(data));
  logNormalizationInfo(data);
  handleTurnFailureState(data, { prompt, intent: 'edit' });
}

function failureType(data) {
  const errors = data.validation?.errors || [];
  const merged = [data.model || '', ...errors, ...(data.normalization_notes || [])].join(' ').toLowerCase();
  if (data.apply_status === 'failed') return 'runtime';
  if (merged.includes('all llm backends failed') || merged.includes('openai') || merged.includes('codex')) {
    return 'backend';
  }
  if (data.apply_status === 'skipped' && data.validation && !data.validation.valid) {
    return 'validation';
  }
  return 'none';
}

function handleTurnFailureState(data, requestBody) {
  if (data.apply_status === 'applied') {
    hideTroubleshootCard();
    return;
  }

  const type = failureType(data);
  const errors = data.validation?.errors || [];
  uiState.failedTurn = {
    prompt: requestBody.prompt,
    intent: requestBody.intent,
    failedCommands: data.effective_commands?.length ? data.effective_commands : (data.commands || []),
    validationErrors: errors,
    type,
    patchId: data.patch_id,
  };
  uiState.repairedCommands = null;
  renderTroubleshootCard();
}

function renderTroubleshootCard(extraSummary = '') {
  if (!dom.troubleshootCard || !uiState.failedTurn) return;

  const type = uiState.failedTurn.type;
  let summary = 'Could not apply that change.';
  if (type === 'backend') {
    summary = 'Model backend unavailable. Open Inspect > LLM Settings, then retry.';
  } else if (type === 'runtime') {
    summary = 'Runtime apply failed. Try Boot, then retry.';
  } else if (type === 'validation') {
    summary = 'Generated commands failed validation. You can run guided diagnose/fix.';
  }
  if (extraSummary) summary = `${summary} ${extraSummary}`;

  if (dom.troubleshootSummary) dom.troubleshootSummary.textContent = summary;
  if (dom.troubleshootBudget) {
    const remaining = Math.max(0, uiState.troubleshootLimit - uiState.troubleshootUsed);
    dom.troubleshootBudget.textContent = `Troubleshoot credits remaining: ${remaining}/${uiState.troubleshootLimit}`;
  }
  if (dom.troubleshootBtn) {
    const canTroubleshoot = type === 'validation' && uiState.troubleshootUsed < uiState.troubleshootLimit;
    dom.troubleshootBtn.disabled = !canTroubleshoot;
  }
  if (dom.applyFixBtn) {
    dom.applyFixBtn.classList.toggle('hidden', !uiState.repairedCommands);
  }
  dom.troubleshootCard.classList.remove('hidden');
}

function hideTroubleshootCard() {
  uiState.failedTurn = null;
  uiState.repairedCommands = null;
  if (dom.troubleshootCard) dom.troubleshootCard.classList.add('hidden');
}

async function runTroubleshoot() {
  if (!uiState.failedTurn || !uiState.sessionId) return;
  if (uiState.failedTurn.type !== 'validation') return;
  const payload = await api('/api/chat/troubleshoot', {
    method: 'POST',
    body: JSON.stringify({
      session_id: uiState.sessionId,
      prompt: uiState.failedTurn.prompt,
      intent: uiState.failedTurn.intent,
      failed_commands: uiState.failedTurn.failedCommands,
      validation_errors: uiState.failedTurn.validationErrors,
    }),
  });
  uiState.troubleshootUsed = payload.budget?.used || uiState.troubleshootUsed + 1;
  uiState.troubleshootLimit = payload.budget?.limit || uiState.troubleshootLimit;
  uiState.repairedCommands = payload.fixed_commands || [];

  const confidence = typeof payload.confidence === 'number' ? ` (confidence ${Math.round(payload.confidence * 100)}%)` : '';
  const reason = payload.reason ? `Reason: ${payload.reason}.` : 'A safe fix was generated.';
  renderTroubleshootCard(`${reason}${confidence}`);
  logMessage('system', `Troubleshoot ready: generated ${uiState.repairedCommands.length} fixed command(s).`);
}

async function applyRepairedCommands() {
  if (!uiState.repairedCommands || !uiState.repairedCommands.length || !uiState.sessionId || !uiState.failedTurn) return;
  const requestBody = {
    session_id: uiState.sessionId,
    prompt: JSON.stringify(uiState.repairedCommands),
    intent: uiState.failedTurn.intent,
  };
  const data = await callChatTurn('repair-apply', requestBody);
  const result = formatTurnResult(data);
  logMessage('system', `${result} (${data.latency_ms}ms)`);
  logNormalizationInfo(data);
  handleTurnFailureState(data, requestBody);
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
      requestBody,
      responseBody: data,
    });
    return data;
  } catch (err) {
    addTraceEntry({
      origin,
      startedAt,
      requestBody,
      error: err.message,
    });
    throw err;
  }
}

function addTraceEntry(entry) {
  traceEntries.unshift(entry);
  if (!dom.traceList) return;

  const details = document.createElement('details');
  details.className = 'trace-item';
  details.open = false;

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
  dom.traceList.prepend(details);
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
  const backend = payload.backend === 'fallback-local' ? 'auto' : (payload.backend || 'auto');
  document.getElementById('llmBackend').value = backend;
  document.getElementById('llmModel').value = payload.model || '';
  document.getElementById('codexCommand').value = payload.codex_command || '';
  document.getElementById('codexModel').value = payload.codex_model || '';
  document.getElementById('llmApiKey').value = '';
  updateSettingsDisclosure(backend);
  const keyInfo = payload.has_api_key ? `saved ${payload.api_key_hint || ''}` : 'not set';
  setSettingsStatus(`LLM settings loaded: backend=${backend}, model=${payload.model}, key=${keyInfo}`);
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
  if (dom.settingsStatus) dom.settingsStatus.textContent = text;
}

function updateSettingsDisclosure(backend) {
  const apiKeyRow = document.getElementById('apiKeyRow');
  const advanced = document.getElementById('advancedSettings');
  if (!apiKeyRow || !advanced) return;
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
  if (!uiState.sessionId) return;
  const data = await api('/api/patch/undo', {
    method: 'POST',
    body: JSON.stringify({ session_id: uiState.sessionId }),
  });
  logMessage('system', `Undo ok for patch ${data.reverted_patch_id}`);
}

function connectEvents() {
  const stream = new EventSource('/api/events/stream');
  stream.onopen = () => setSseState('connected');
  stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      logEvent(`[${payload.source}] ${payload.message}`);
    } catch {
      logEvent(event.data);
    }
  };
  stream.onerror = () => {
    setSseState('reconnecting');
    logEvent('event stream disconnected');
  };
}

function switchView(viewName) {
  document.querySelectorAll('.view').forEach((view) => {
    const shouldShow = view.id === `view-${viewName}`;
    view.classList.toggle('hidden', !shouldShow);
  });
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.view === viewName);
  });
}

function initModeNav() {
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });
}

function initActions() {
  document.getElementById('bootBtn').onclick = () => boot().catch((e) => {
    setRuntimeState('error');
    logMessage('system', e.message);
  });
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
  document.getElementById('llmBackend').onchange = (e) => updateSettingsDisclosure(e.target.value);

  document.querySelectorAll('.quickPromptBtn').forEach((btn) => {
    btn.onclick = () => sendQuickPrompt(btn.dataset.prompt).catch((e) => logMessage('system', e.message));
  });

  const clearTraceBtn = document.getElementById('clearTraceBtn');
  if (clearTraceBtn) {
    clearTraceBtn.onclick = () => {
      if (dom.traceList) dom.traceList.textContent = '';
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

  if (dom.troubleshootBtn) {
    dom.troubleshootBtn.onclick = () => runTroubleshoot().catch((e) => {
      logMessage('system', `Troubleshoot failed: ${e.message}`);
      renderTroubleshootCard();
    });
  }
  if (dom.applyFixBtn) {
    dom.applyFixBtn.onclick = () => applyRepairedCommands().catch((e) => logMessage('system', e.message));
  }
  if (dom.dismissFixBtn) {
    dom.dismissFixBtn.onclick = () => hideTroubleshootCard();
  }
}

renderStatus();
initModeNav();
initActions();
connectEvents();
boot().catch((e) => {
  setRuntimeState('error');
  logMessage('system', e.message);
});
