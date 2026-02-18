const statusLine = document.getElementById('statusLine');
const messages = document.getElementById('messages');
const eventsBox = document.getElementById('eventsBox');
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

  const data = await api('/api/chat/turn', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, prompt, intent }),
  });
  const result = data.validation.valid ? `Applied patch #${data.patch_id}` : `Rejected: ${data.validation.errors.join('; ')}`;
  logMessage('system', `${result} (${data.latency_ms}ms)`);
}

async function applyMixer() {
  if (!sessionId) await boot();
  const commands = [
    { op: 'player_set', player: 'p1', param: 'amp', value: Number(document.getElementById('p1_amp').value) },
    { op: 'player_set', player: 'p1', param: 'lpf', value: Number(document.getElementById('p1_lpf').value) },
    { op: 'player_set', player: 'p1', param: 'hpf', value: Number(document.getElementById('p1_hpf').value) },
    { op: 'player_set', player: 'p1', param: 'pan', value: Number(document.getElementById('p1_pan').value) },
  ];
  const mixerTurn = await api('/api/chat/turn', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, prompt: JSON.stringify(commands), intent: 'mix_fix' }),
  });
  logMessage('system', `Mixer updated via patch #${mixerTurn.patch_id}`);
}

async function setBpm() {
  if (!sessionId) await boot();
  const bpm = Number(document.getElementById('bpmInput').value);
  const prompt = `Set bpm to ${bpm}`;
  await api('/api/chat/turn', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, prompt, intent: 'edit' }),
  });
  logMessage('system', `Requested BPM ${bpm}`);
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

connectEvents();
boot().catch((e) => logMessage('system', e.message));
