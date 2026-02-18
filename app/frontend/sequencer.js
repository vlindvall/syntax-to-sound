const sequencerRows = document.getElementById('sequencerRows');
const sequencerStatus = document.getElementById('sequencerStatus');
const sequencerClock = document.getElementById('sequencerClock');
const sequencerRuntimePill = document.getElementById('sequencerRuntimePill');
const sequencerSessionPill = document.getElementById('sequencerSessionPill');
const sequencerPlayersPill = document.getElementById('sequencerPlayersPill');
const songPathInput = document.getElementById('songPath');
const addTypeInput = document.getElementById('addType');
const addPlayerPreviewInput = document.getElementById('addPlayerPreview');
const addSynthInput = document.getElementById('addSynth');
const addPatternInput = document.getElementById('addPattern');
const addDurInput = document.getElementById('addDur');
const addAmpInput = document.getElementById('addAmp');
const addSequenceBtn = document.getElementById('addSequenceBtn');
const sequencerMeta = new Map();
const playerAmpMemory = new Map();
const DEFAULT_PLAYER_TYPES = ['p', 'b', 'd', 'h', 'n'];
const PLAYER_TYPE_LABELS = {
  p: 'Melody',
  b: 'Bass',
  d: 'Drums',
  h: 'Hi-Hat',
  n: 'Noise/FX',
};
const PLAYER_DEFAULT_SYNTH = {
  p: 'pluck',
  b: 'bass',
  d: 'play',
  h: 'play',
  n: 'noise',
};
const PLAYER_PATTERN_EXAMPLES = {
  p: '[0,2,4,7]',
  b: '[0,-2,-4,0]',
  d: '"x-o-x-o-"',
  h: '"-*-*"',
  n: '[0]',
};

let sessionId = null;
let runtimeState = null;
let runtimePollTimer = null;
let sequencerFrameHandle = null;
let serverTimeOffsetSec = 0;
let lastRuntimeStateFingerprint = '';
let lastAutoSynthValue = addSynthInput?.value?.trim() || 'pluck';

function setSequencerStatus(text) {
  if (sequencerStatus) sequencerStatus.textContent = text;
}

function updateHeaderPills() {
  if (sequencerRuntimePill) {
    const isRunning = Boolean(runtimeState?.is_running);
    sequencerRuntimePill.textContent = isRunning ? 'ready' : 'idle';
  }
  if (sequencerSessionPill) {
    sequencerSessionPill.textContent = sessionId ? `${sessionId.slice(0, 8)}...` : 'n/a';
  }
  if (sequencerPlayersPill) {
    const count = Object.keys(runtimeState?.players || {}).length;
    sequencerPlayersPill.textContent = String(count);
  }
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
  setSequencerStatus(`Runtime booted: ${data.status} (${sessionId})`);
  await refreshRuntimeState(true);
}

async function loadSong() {
  if (!sessionId) await boot();
  const path = songPathInput.value.trim();
  if (!path) return;
  await api('/api/runtime/load-song', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
  setSequencerStatus(`Loaded song: ${path}`);
  await refreshRuntimeState(true);
}

async function callSequencerPatch(commands) {
  if (!sessionId) {
    await refreshRuntimeState(false);
  }
  if (!sessionId) {
    await boot();
  }

  const data = await api('/api/chat/turn', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      prompt: JSON.stringify(commands),
      intent: 'edit',
    }),
  });

  if (data.validation?.valid && data.apply_status === 'applied') {
    setSequencerStatus(`Applied patch #${data.patch_id}`);
    await refreshRuntimeState(true);
    return data;
  }

  const errors = (data.validation?.errors || []).join('; ') || data.apply_status;
  setSequencerStatus(`Patch not applied: ${errors}`);
  await refreshRuntimeState(false);
  throw new Error(errors);
}

function splitTopLevel(text) {
  const parts = [];
  let current = '';
  let depth = 0;
  let quote = '';

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      current += ch;
      if (ch === quote && text[i - 1] !== '\\') {
        quote = '';
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === '[' || ch === '(' || ch === '{') {
      depth += 1;
      current += ch;
      continue;
    }
    if (ch === ']' || ch === ')' || ch === '}') {
      depth = Math.max(0, depth - 1);
      current += ch;
      continue;
    }
    if (ch === ',' && depth === 0) {
      if (current.trim()) parts.push(current.trim());
      current = '';
      continue;
    }
    current += ch;
  }

  if (current.trim()) parts.push(current.trim());
  return parts;
}

function normalizePatternSource(pattern) {
  if (typeof pattern !== 'string') return '';
  return pattern.trim();
}

function parsePatternTokens(pattern) {
  const source = normalizePatternSource(pattern);
  if (!source) return ['-'];

  if ((source.startsWith('"') && source.endsWith('"')) || (source.startsWith("'") && source.endsWith("'"))) {
    const unquoted = source.slice(1, -1);
    if (!unquoted) return ['-'];
    return unquoted.split('');
  }

  if (source.startsWith('P[') && source.endsWith(']')) {
    const inner = source.slice(2, -1);
    const parts = splitTopLevel(inner);
    return parts.length ? parts : ['-'];
  }

  if (source.startsWith('[') && source.endsWith(']')) {
    const inner = source.slice(1, -1);
    const parts = splitTopLevel(inner);
    return parts.length ? parts : ['-'];
  }

  if (source.startsWith('(') && source.endsWith(')')) {
    const inner = source.slice(1, -1);
    const parts = splitTopLevel(inner);
    return parts.length ? parts : [source];
  }

  return [source];
}

function parseDurBeats(rawDur) {
  if (typeof rawDur === 'number' && Number.isFinite(rawDur) && rawDur > 0) {
    return rawDur;
  }
  if (typeof rawDur !== 'string') return 1;

  const source = rawDur.trim();
  if (!source) return 1;

  if (/^\d+(\.\d+)?$/.test(source)) {
    const value = Number(source);
    return Number.isFinite(value) && value > 0 ? value : 1;
  }

  const fraction = source.match(/^(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/);
  if (fraction) {
    const top = Number(fraction[1]);
    const bottom = Number(fraction[2]);
    if (Number.isFinite(top) && Number.isFinite(bottom) && bottom > 0) {
      const value = top / bottom;
      return value > 0 ? value : 1;
    }
  }

  return 1;
}

function comparePlayers(a, b) {
  const ma = a.match(/^([a-zA-Z]+)(\d+)$/);
  const mb = b.match(/^([a-zA-Z]+)(\d+)$/);
  if (!ma || !mb) return a.localeCompare(b);
  if (ma[1] !== mb[1]) return ma[1].localeCompare(mb[1]);
  return Number(ma[2]) - Number(mb[2]);
}

function getCurrentBpm() {
  const raw = runtimeState?.globals?.['Clock.bpm'];
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw;
  if (typeof raw === 'string') {
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return 120;
}

function toFiniteNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function getPlayerAmp(player) {
  if (!player || typeof player !== 'object') return null;
  const fromKwargs = player.kwargs && typeof player.kwargs === 'object' ? player.kwargs.amp : null;
  if (fromKwargs !== null && fromKwargs !== undefined) return fromKwargs;
  if (player.amp !== null && player.amp !== undefined) return player.amp;
  return null;
}

function isMutedAmpValue(ampValue) {
  const numeric = toFiniteNumber(ampValue);
  return numeric !== null && numeric === 0;
}

function rememberAmpIfUsable(playerName, ampValue) {
  const numeric = toFiniteNumber(ampValue);
  if (numeric !== null && numeric > 0) {
    playerAmpMemory.set(playerName, numeric);
  }
}

async function togglePlayerMute(playerName, player) {
  const currentAmp = getPlayerAmp(player);
  const isMuted = isMutedAmpValue(currentAmp);

  if (!isMuted) {
    rememberAmpIfUsable(playerName, currentAmp);
    await callSequencerPatch([{ op: 'player_set', player: playerName, param: 'amp', value: 0 }]);
    return;
  }

  const restoreAmp = playerAmpMemory.get(playerName) ?? 0.8;
  await callSequencerPatch([
    { op: 'player_set', player: playerName, param: 'amp', value: restoreAmp },
  ]);
}

async function applySequencerEdit(player, synthInput, patternInput, durInput, existingPlayer) {
  const synth = synthInput.value.trim() || existingPlayer.synth || 'play';
  const pattern = patternInput.value.trim() || existingPlayer.pattern || '0';
  const kwargs =
    existingPlayer.kwargs && typeof existingPlayer.kwargs === 'object'
      ? { ...existingPlayer.kwargs }
      : {};

  const durValue = Number(durInput.value);
  if (Number.isFinite(durValue) && durValue > 0) {
    kwargs.dur = durValue;
  } else {
    delete kwargs.dur;
  }

  await callSequencerPatch([
    {
      op: 'player_assign',
      player,
      synth,
      pattern,
      kwargs,
    },
  ]);
}

async function stopSequencerPlayer(player) {
  await callSequencerPatch([{ op: 'player_stop', player }]);
}

function defaultSynthForType(type) {
  const prefix = typeof type === 'string' && type.length > 0 ? type[0].toLowerCase() : 'p';
  return PLAYER_DEFAULT_SYNTH[prefix] || 'pluck';
}

function extractPlayerType(playerName) {
  if (typeof playerName !== 'string') return null;
  const match = playerName.match(/^([a-z])[1-9][0-9]*$/);
  return match ? match[1] : null;
}

function availablePlayerTypes() {
  const discoveredExtras = new Set();
  const players = runtimeState?.players || {};
  for (const playerName of Object.keys(players)) {
    const type = extractPlayerType(playerName);
    if (type && !DEFAULT_PLAYER_TYPES.includes(type)) {
      discoveredExtras.add(type);
    }
  }
  return [...DEFAULT_PLAYER_TYPES, ...Array.from(discoveredExtras).sort()];
}

function updateAddTypeOptions() {
  if (!addTypeInput) return;
  const previous = addTypeInput.value;
  const types = availablePlayerTypes();
  addTypeInput.textContent = '';
  for (const type of types) {
    const option = document.createElement('option');
    option.value = type;
    option.textContent = `${PLAYER_TYPE_LABELS[type] || 'Custom'} (${type})`;
    addTypeInput.appendChild(option);
  }
  if (types.includes(previous)) {
    addTypeInput.value = previous;
    return;
  }
  addTypeInput.value = types[0] || 'p';
}

function patternExampleForType(type) {
  const key = typeof type === 'string' ? type.toLowerCase() : 'p';
  return PLAYER_PATTERN_EXAMPLES[key] || '[0,2,4,7]';
}

function updatePatternExampleForSelectedType() {
  if (!addPatternInput) return;
  const example = patternExampleForType(selectedPlayerType());
  addPatternInput.placeholder = `pattern (example: ${example})`;
}

function selectedPlayerType() {
  const value = addTypeInput?.value?.trim().toLowerCase() || 'p';
  const types = availablePlayerTypes();
  return types.includes(value) ? value : (types[0] || 'p');
}

function parsePlayerIndex(playerName, expectedType) {
  if (typeof playerName !== 'string') return null;
  const match = playerName.match(/^([a-z])([1-9][0-9]*)$/);
  if (!match) return null;
  if (expectedType && match[1] !== expectedType) return null;
  return Number(match[2]);
}

function nextPlayerForType(type) {
  const selectedType = typeof type === 'string' && type.length > 0 ? type[0].toLowerCase() : 'p';
  const players = runtimeState?.players || {};
  let maxIndex = 0;
  for (const playerName of Object.keys(players)) {
    const index = parsePlayerIndex(playerName, selectedType);
    if (index !== null && index > maxIndex) {
      maxIndex = index;
    }
  }
  return `${selectedType}${maxIndex + 1}`;
}

function updateAddPlayerPreview() {
  if (!addPlayerPreviewInput) return;
  addPlayerPreviewInput.value = nextPlayerForType(selectedPlayerType());
}

function applyAutoSynthForSelectedType(force = false) {
  if (!addTypeInput || !addSynthInput) return;
  const nextDefault = defaultSynthForType(addTypeInput.value);
  const current = addSynthInput.value.trim();
  if (force || !current || current === lastAutoSynthValue) {
    addSynthInput.value = nextDefault;
  }
  lastAutoSynthValue = nextDefault;
}

function parsePositiveNumberInput(input, fieldName) {
  if (!input) return null;
  const raw = input.value.trim();
  if (!raw) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${fieldName} must be a positive number`);
  }
  return parsed;
}

function parseNonNegativeNumberInput(input, fieldName) {
  if (!input) return null;
  const raw = input.value.trim();
  if (!raw) return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${fieldName} must be a non-negative number`);
  }
  return parsed;
}

async function addSequenceFromComposer() {
  const playerType = selectedPlayerType();
  const player = nextPlayerForType(playerType);
  const synth = addSynthInput?.value?.trim() || 'pluck';
  const patternRaw = addPatternInput?.value?.trim() || '';
  const pattern = patternRaw || patternExampleForType(playerType);
  if (!player) {
    throw new Error('Player is required');
  }

  const kwargs = {};
  const dur = parsePositiveNumberInput(addDurInput, 'Dur');
  if (dur !== null) kwargs.dur = dur;
  const amp = parseNonNegativeNumberInput(addAmpInput, 'Amp');
  if (amp !== null) kwargs.amp = amp;

  await callSequencerPatch([
    {
      op: 'player_assign',
      player,
      synth,
      pattern,
      kwargs,
    },
  ]);
}

function renderSequencer() {
  if (!sequencerRows) return;
  sequencerRows.textContent = '';
  sequencerMeta.clear();

  if (!runtimeState) {
    updateHeaderPills();
    setSequencerStatus('Waiting for runtime state...');
    return;
  }

  const players = runtimeState.players || {};
  const playerNames = Object.keys(players).sort(comparePlayers);
  const bpm = getCurrentBpm();
  const songPath = runtimeState.song_path || '(manual patching)';
  updateHeaderPills();

  if (songPathInput && songPath && !songPathInput.value) {
    songPathInput.value = songPath;
  }
  updateAddTypeOptions();
  updatePatternExampleForSelectedType();
  updateAddPlayerPreview();

  if (!playerNames.length) {
    setSequencerStatus(`No active player assignments. Song: ${songPath}`);
    return;
  }

  setSequencerStatus(`Song: ${songPath} | ${playerNames.length} players | ${bpm} BPM`);

  for (const playerName of playerNames) {
    const player = players[playerName] || {};
    const pattern = typeof player.pattern === 'string' ? player.pattern : '0';
    const tokens = parsePatternTokens(pattern).slice(0, 128);
    const durBeats = parseDurBeats(player.kwargs?.dur ?? player.dur);
    const ampValue = getPlayerAmp(player);
    const isMuted = isMutedAmpValue(ampValue);
    rememberAmpIfUsable(playerName, ampValue);

    const row = document.createElement('div');
    row.className = 'sequencer-row';

    const header = document.createElement('div');
    header.className = 'sequencer-head';
    const synthName = player.synth || 'play';
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = playerName;
    const synthLabel = document.createElement('span');
    synthLabel.className = 'synth';
    synthLabel.textContent = synthName;
    const durLabel = document.createElement('span');
    durLabel.className = 'dur';
    const ampLabel =
      ampValue === null || ampValue === undefined ? 'n/a' : String(ampValue);
    durLabel.textContent = `dur=${durBeats} | amp=${ampLabel}${isMuted ? ' (muted)' : ''}`;
    header.appendChild(chip);
    header.appendChild(synthLabel);
    header.appendChild(durLabel);
    row.appendChild(header);

    const controls = document.createElement('div');
    controls.className = 'sequencer-controls';

    const synthInput = document.createElement('input');
    synthInput.value = synthName;
    synthInput.placeholder = 'synth';

    const patternInput = document.createElement('input');
    patternInput.value = pattern;
    patternInput.placeholder = 'pattern';

    const durInput = document.createElement('input');
    durInput.type = 'number';
    durInput.min = '0.03125';
    durInput.step = '0.03125';
    durInput.value = String(durBeats);

    const applyBtn = document.createElement('button');
    applyBtn.className = 'secondary';
    applyBtn.textContent = 'Apply';
    applyBtn.onclick = () =>
      applySequencerEdit(playerName, synthInput, patternInput, durInput, player).catch((e) =>
        setSequencerStatus(`Edit failed: ${e.message}`),
      );

    const muteBtn = document.createElement('button');
    muteBtn.className = isMuted ? 'secondary' : 'mute-small';
    muteBtn.textContent = isMuted ? 'Unmute' : 'Mute';
    muteBtn.onclick = () =>
      togglePlayerMute(playerName, player).catch((e) =>
        setSequencerStatus(`Mute failed: ${e.message}`),
      );

    const stopBtn = document.createElement('button');
    stopBtn.className = 'stop-small';
    stopBtn.textContent = 'Stop';
    stopBtn.onclick = () =>
      stopSequencerPlayer(playerName).catch((e) => setSequencerStatus(`Stop failed: ${e.message}`));

    controls.appendChild(synthInput);
    controls.appendChild(patternInput);
    controls.appendChild(durInput);
    controls.appendChild(applyBtn);
    controls.appendChild(muteBtn);
    controls.appendChild(stopBtn);
    row.appendChild(controls);

    const steps = document.createElement('div');
    steps.className = 'sequence-steps';
    const cells = [];
    tokens.forEach((token, index) => {
      const cell = document.createElement('div');
      cell.className = 'step-cell';
      cell.dataset.index = String(index);
      cell.textContent = token;
      steps.appendChild(cell);
      cells.push(cell);
    });
    row.appendChild(steps);

    sequencerMeta.set(playerName, {
      durBeats,
      stepCount: cells.length,
      cells,
      activeIndex: -1,
    });

    sequencerRows.appendChild(row);
  }
}

function updateSequencerClock() {
  if (!runtimeState || !sequencerClock) return;
  if (!runtimeState.clock_started_at) {
    sequencerClock.textContent = 'Clock stopped';
    for (const meta of sequencerMeta.values()) {
      if (meta.activeIndex >= 0) {
        meta.cells[meta.activeIndex].classList.remove('active');
        meta.activeIndex = -1;
      }
    }
    return;
  }

  const bpm = getCurrentBpm();
  const nowSec = Date.now() / 1000 + serverTimeOffsetSec;
  const elapsedSec = Math.max(0, nowSec - runtimeState.clock_started_at);
  const elapsedBeats = elapsedSec * (bpm / 60);
  sequencerClock.textContent = `Now playing | beat ${elapsedBeats.toFixed(2)} | ${bpm} BPM`;

  for (const meta of sequencerMeta.values()) {
    if (!meta.stepCount) continue;
    const stepPosition = Math.floor(elapsedBeats / meta.durBeats) % meta.stepCount;
    if (stepPosition === meta.activeIndex) continue;

    if (meta.activeIndex >= 0) {
      meta.cells[meta.activeIndex].classList.remove('active');
    }
    meta.cells[stepPosition].classList.add('active');
    meta.activeIndex = stepPosition;
  }
}

function startSequencerAnimation() {
  if (sequencerFrameHandle) return;
  const tick = () => {
    updateSequencerClock();
    sequencerFrameHandle = requestAnimationFrame(tick);
  };
  sequencerFrameHandle = requestAnimationFrame(tick);
}

function runtimeFingerprint(payload) {
  return JSON.stringify({
    song_path: payload.song_path,
    clock_started_at: payload.clock_started_at,
    globals: payload.globals,
    players: payload.players,
  });
}

async function refreshRuntimeState(forceRender = false) {
  const payload = await api('/api/runtime/state');
  runtimeState = payload;

  if (payload.session_id) {
    sessionId = payload.session_id;
  }
  if (typeof payload.server_ts === 'number') {
    serverTimeOffsetSec = payload.server_ts - Date.now() / 1000;
  }

  const fingerprint = runtimeFingerprint(payload);
  if (forceRender || fingerprint !== lastRuntimeStateFingerprint) {
    lastRuntimeStateFingerprint = fingerprint;
    renderSequencer();
    return;
  }
  updateHeaderPills();
}

function startRuntimeStatePolling() {
  if (runtimePollTimer) return;
  runtimePollTimer = setInterval(() => {
    refreshRuntimeState(false).catch((e) => setSequencerStatus(`State unavailable: ${e.message}`));
  }, 1000);
}

function connectEvents() {
  const stream = new EventSource('/api/events/stream');
  stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.source === 'patch' || payload.source === 'runtime') {
        refreshRuntimeState(false).catch(() => undefined);
      }
    } catch {
      // no-op
    }
  };
}

document.getElementById('bootBtn').onclick = () => boot().catch((e) => setSequencerStatus(e.message));
document.getElementById('loadBtn').onclick = () => loadSong().catch((e) => setSequencerStatus(e.message));
document.getElementById('refreshBtn').onclick = () =>
  refreshRuntimeState(true).catch((e) => setSequencerStatus(e.message));
if (addSequenceBtn) {
  addSequenceBtn.onclick = () =>
    addSequenceFromComposer()
      .then(() => {
        if (addPatternInput) addPatternInput.value = '';
      })
      .catch((e) => setSequencerStatus(`Add failed: ${e.message}`));
}
if (addTypeInput) {
  addTypeInput.onchange = () => {
    applyAutoSynthForSelectedType();
    updatePatternExampleForSelectedType();
    updateAddPlayerPreview();
  };
}

updateAddTypeOptions();
updatePatternExampleForSelectedType();
updateAddPlayerPreview();
applyAutoSynthForSelectedType(true);
connectEvents();
startRuntimeStatePolling();
startSequencerAnimation();
refreshRuntimeState(true).catch((e) => setSequencerStatus(`State unavailable: ${e.message}`));
